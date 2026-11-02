"""Question orchestration.

The only place where the AI layer and the analytics layer meet. The order is
fixed and enforced by the code below:

    question -> interpretation -> plan(s) -> validation -> deterministic
    analytics -> evidence -> explanation -> answer

The explanation receives an evidence package, not the raw data. If the LLM
later produces something unsupported, validation stops it before a single row
is read.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from app.ai.base import Interpretation
from app.ai.factory import AIPipeline
from app.core.errors import AppError, QuestionRejectedError
from app.core.logging import get_logger
from app.data.repository import DatasetRepository
from app.models.enums import AnswerStatus
from app.models.catalog import METRIC_CATALOG
from app.schemas.analysis import AnalysisResult
from app.schemas.evidence import EvidencePackage
from app.schemas.question import (
    Answer,
    Explanation,
    QuestionInterpretation,
    QuestionRequest,
)
from app.services.analysis_service import AnalysisService

logger = get_logger(__name__)


class QuestionService:
    """Answers natural-language questions from the bundled datasets."""

    def __init__(
        self,
        repository: DatasetRepository,
        analysis_service: AnalysisService,
        pipeline: AIPipeline,
    ) -> None:
        self.repository = repository
        self.analysis_service = analysis_service
        self.pipeline = pipeline

    def ask(self, request: QuestionRequest) -> Answer:
        started = time.perf_counter()
        question = request.question

        interpretation = self.pipeline.interpreter.interpret(question)
        if not interpretation.is_actionable:
            return self._unsupported(question, interpretation, started)

        plans = self.pipeline.planner.plan(interpretation)
        if not plans:  # pragma: no cover - planner raises instead
            raise QuestionRejectedError(
                "No analysis plan could be produced for this question.",
                details={"question": question},
            )

        results: list[AnalysisResult] = []
        caveats: list[str] = []
        for plan in plans:
            try:
                results.append(
                    self.analysis_service.execute(plan, persist=request.persist)
                )
            except AppError as error:
                logger.info(
                    "plan rejected during question handling: %s", error.code, extra={"error": error.code}
                )
                caveats.append(f"{error.code}: {error.message}")

        if not results:
            return self._failed(question, interpretation, caveats, started)

        evidence = (
            self.analysis_service.evidence_for(results)
            if request.include_evidence
            else EvidencePackage()
        )
        draft = self.pipeline.explainer.explain(
            question=question, interpretation=interpretation, evidence=evidence
        )

        caveats.extend(self._global_caveats(interpretation, evidence))
        for result in results:
            caveats.extend(result.warnings)
        if not self.pipeline.llm_enabled:
            caveats.append(
                "No LLM provider is configured. The narrative below was assembled from "
                "evidence by template; all figures are deterministic."
            )

        return Answer(
            answer_id=f"an_{uuid4().hex[:16]}",
            status=AnswerStatus.PARTIALLY_ANSWERED if caveats and len(results) < len(plans) else AnswerStatus.ANSWERED,
            question=question,
            interpretation=to_schema(interpretation),
            plan=results[0].plan if results else None,
            analyses=results,
            evidence=evidence,
            explanation=Explanation(
                summary=draft.summary,
                detail=draft.detail,
                findings=list(draft.findings),
                grounded_on=list(draft.grounded_on),
                provider=draft.provider,
                model=draft.model,
                generated_at=datetime.now(timezone.utc).isoformat(),
            ),
            caveats=caveats,
            llm_enabled=self.pipeline.llm_enabled,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    # -- non-happy paths ----------------------------------------------------
    def _unsupported(
        self, question: str, interpretation: Interpretation, started: float
    ) -> Answer:
        topics = sorted(
            {spec.label for spec in METRIC_CATALOG.values()}
        )
        answer = Answer(
            answer_id=f"an_{uuid4().hex[:16]}",
            status=AnswerStatus.UNSUPPORTED,
            question=question,
            interpretation=to_schema(interpretation),
            analyses=[],
            evidence=EvidencePackage(),
            explanation=Explanation(
                summary=(
                    "FinSight could not map this question onto the financial data it has. "
                    "It answers questions about the bundled income statement, expense ledger, "
                    "budgets and vendor register."
                ),
                detail="Supported metrics include: " + ", ".join(topics[:12]) + ".",
                findings=[
                    "Try naming a metric and a quarter, for example: "
                    "'Why did operating expenses increase in 2024-Q3?'"
                ],
                grounded_on=[],
                provider=self.pipeline.explainer.name,
                model=self.pipeline.explainer.model,
                generated_at=datetime.now(timezone.utc).isoformat(),
            ),
            caveats=["No catalogued metric was matched in the question."],
            llm_enabled=self.pipeline.llm_enabled,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("question unsupported: %s", question)
        return answer

    def _failed(
        self,
        question: str,
        interpretation: Interpretation,
        caveats: list[str],
        started: float,
    ) -> Answer:
        return Answer(
            answer_id=f"an_{uuid4().hex[:16]}",
            status=AnswerStatus.FAILED,
            question=question,
            interpretation=to_schema(interpretation),
            analyses=[],
            evidence=EvidencePackage(),
            explanation=None,
            caveats=caveats or ["No analysis could be executed for this question."],
            llm_enabled=self.pipeline.llm_enabled,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _global_caveats(interpretation: Interpretation, evidence: EvidencePackage) -> list[str]:
        caveats: list[str] = []
        if interpretation.period and interpretation.period not in evidence.periods_covered:
            caveats.append(
                f"The requested period {interpretation.period} produced no evidence rows."
            )
        if not evidence.datasets_used:
            caveats.append("No datasets contributed to this answer.")
        return caveats


def to_schema(interpretation: Interpretation) -> QuestionInterpretation:
    """Convert the AI-layer dataclass into its transport contract."""
    return QuestionInterpretation(
        restated_question=interpretation.restated_question,
        intent=interpretation.intent,
        analysis_type=interpretation.analysis_type,
        metric=interpretation.metric,
        period=interpretation.period,
        comparison_period=interpretation.comparison_period,
        dimensions=list(interpretation.dimensions),
        strategy=interpretation.strategy,
        confidence=interpretation.confidence,
        notes=list(interpretation.notes),
    )