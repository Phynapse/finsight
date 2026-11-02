"""AI pipeline wiring.

Phase 1 resolves to the deterministic implementations. Phase 2 adds an LLM
provider behind the same interfaces; :func:`build_pipeline` is the only place
that decides which implementation is in use, and the rest of the application is
unaffected by that choice.

The important property is that the LLM is optional and *advisory*: with no API
key configured, FinSight still answers, because every figure it reports was
computed by Python.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.base import (
    AnalysisPlanner,
    ExplanationGenerator,
    Interpretation,
    LLMConfig,
    QuestionInterpreter,
)
from app.ai.rules import (
    DeterministicAnalysisPlanner,
    DeterministicQuestionInterpreter,
    RuleBasedExplanationGenerator,
)
from app.core.config import Settings
from app.core.errors import LLMNotConfiguredError
from app.core.logging import get_logger
from app.data.repository import DatasetRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AIPipeline:
    """The three collaborators the question service orchestrates."""

    interpreter: QuestionInterpreter
    planner: AnalysisPlanner
    explainer: ExplanationGenerator
    llm_config: LLMConfig

    @property
    def llm_enabled(self) -> bool:
        return self.llm_config.is_configured

    def describe(self) -> dict[str, str]:
        return {
            "interpreter": self.interpreter.name,
            "planner": self.planner.name,
            "explainer": self.explainer.name,
            "model": self.llm_config.model or "none",
        }


def build_pipeline(settings: Settings, repository: DatasetRepository) -> AIPipeline:
    """Assemble the AI layer for this process.

    A language model is only wired in once a provider *and* an API key are both
    configured. Until then the deterministic implementations run, and the
    explanation says so.
    """
    config = LLMConfig(
        provider=settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key_value,
        timeout_seconds=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
    )

    if settings.llm_provider != "disabled" and settings.llm_api_key_value is None:
        logger.warning(
            "LLM provider '%s' selected but no API key is configured; "
            "using deterministic implementations instead.",
            settings.llm_provider,
        )

    return AIPipeline(
        interpreter=DeterministicQuestionInterpreter(repository),
        planner=DeterministicAnalysisPlanner(repository),
        explainer=RuleBasedExplanationGenerator(repository),
        llm_config=config,
    )


def require_llm(config: LLMConfig) -> None:
    """Guard for Phase 2 endpoints that genuinely need a live model."""
    if not config.is_configured:
        raise LLMNotConfiguredError(details={"provider": config.provider})


def describe_interpretation(interpretation: Interpretation) -> str:
    return f"{interpretation.strategy}: {interpretation.intent}"