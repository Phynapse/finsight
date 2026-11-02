"""The AI layer's contracts.

This module defines *what* a language model is allowed to do in FinSight, and
nothing else. Three narrow interfaces, each returning a typed structure:

``QuestionInterpreter``
    natural language -> :class:`Interpretation` (catalogued intent only)
``AnalysisPlanner``
    :class:`Interpretation` -> :class:`AnalysisPlan` (catalogued plan only)
``ExplanationGenerator``
    evidence package -> :class:`ExplanationDraft`

The guarantees that matter:

* the model never queries a file, a database or a dataframe,
* the model never performs arithmetic on financial values,
* the model never emits SQL, code or a file path,
* everything it returns is re-validated by
  :class:`app.analytics.validator.PlanValidator` before a single row is read,
  and the evidence it may cite is enumerated for it in the request.

Phase 1 ships only the deterministic implementations in
:mod:`app.ai.rules`. A real provider is added behind these interfaces in the
next phase and nothing above this layer has to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.models.enums import AnalysisType
from app.schemas.analysis import AnalysisPlan
from app.schemas.evidence import EvidencePackage


@dataclass(frozen=True, slots=True)
class Interpretation:
    """What the user is asking, expressed only in catalogued terms."""

    restated_question: str
    intent: str
    analysis_type: AnalysisType | None = None
    metric: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    comparison_mode: str = "none"
    dimensions: tuple[str, ...] = ()
    strategy: str = "llm"
    confidence: float = 0.0
    notes: tuple[str, ...] = field(default=())

    @property
    def is_actionable(self) -> bool:
        return self.analysis_type is not None and self.metric is not None


@dataclass(frozen=True, slots=True)
class ExplanationDraft:
    """A narrative plus the evidence item IDs it is allowed to have read."""

    summary: str
    detail: str = ""
    findings: tuple[str, ...] = ()
    grounded_on: tuple[str, ...] = ()
    provider: str = "llm"
    model: str | None = None


@runtime_checkable
class QuestionInterpreter(Protocol):
    """Turn a natural-language question into a catalogued interpretation."""

    name: str

    def interpret(self, question: str) -> Interpretation: ...


@runtime_checkable
class AnalysisPlanner(Protocol):
    """Turn an interpretation into a validated, closed-form analysis plan."""

    name: str

    def plan(self, interpretation: Interpretation) -> list[AnalysisPlan]: ...


@runtime_checkable
class ExplanationGenerator(Protocol):
    """Explain a bounded evidence package. Never introduces a new number."""

    name: str
    model: str | None

    def explain(
        self,
        *,
        question: str,
        interpretation: Interpretation,
        evidence: EvidencePackage,
    ) -> ExplanationDraft: ...


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """The only configuration an LLM provider receives."""

    provider: str
    model: str
    base_url: str
    api_key: str | None
    timeout_seconds: int
    max_tokens: int

    @property
    def is_configured(self) -> bool:
        return self.provider != "disabled" and bool(self.api_key)


PLAN_CONTRACT: dict[str, object] = {
    "description": (
        "The only JSON object an LLM planner may return. Every value must be a "
        "catalogued identifier; unknown values are rejected before execution."
    ),
    "required": ["analysis_type", "metric"],
    "properties": {
        "analysis_type": {
            "enum": [
                "metric_snapshot",
                "revenue_performance",
                "expense_analysis",
                "expense_variance",
                "profitability",
                "budget_variance",
                "vendor_spend",
                "trend",
            ]
        },
        "metric": {"type": "string", "description": "A metric id from the metric catalog."},
        "period": {"type": "string", "pattern": r"^\d{4}-Q[1-4]$"},
        "period_end": {"type": "string", "pattern": r"^\d{4}-Q[1-4]$"},
        "comparison_period": {"type": "string", "pattern": r"^\d{4}-Q[1-4]$"},
        "comparison_mode": {"enum": ["none", "prior_quarter", "prior_year"]},
        "dimensions": {
            "type": "array",
            "items": {
                "enum": ["department", "category", "vendor", "month", "quarter"],
            },
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["field", "values"],
                "properties": {
                    "field": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "granularity": {"enum": ["quarter", "month", "vendor"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
    },
}

INTERPRETATION_CONTRACT: dict[str, object] = {
    "description": (
        "What a question interpreter may return. Catalogued metric and analysis "
        "type identifiers only; no SQL, no code, no file references."
    ),
    "required": ["restated_question", "intent"],
    "properties": {
        "restated_question": {"type": "string"},
        "intent": {"type": "string"},
        "analysis_type": {"enum": PLAN_CONTRACT["properties"]["analysis_type"]["enum"]},  # type: ignore[index]
        "metric": {"type": "string"},
        "period": {"type": "string"},
        "comparison_period": {"type": "string"},
        "comparison_mode": {"enum": ["none", "prior_quarter", "prior_year"]},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}