"""Question / answer contracts for the natural-language entry point."""

from __future__ import annotations

from pydantic import Field, field_validator

from app.models.enums import AnswerStatus, AnalysisType
from app.schemas.analysis import AnalysisPlan, AnalysisResult, _StrictModel
from app.schemas.evidence import EvidencePackage


class QuestionRequest(_StrictModel):
    """Body of ``POST /questions``."""

    question: str = Field(min_length=3, max_length=500)
    include_evidence: bool = True
    persist: bool = True

    @field_validator("question")
    @classmethod
    def question_must_be_meaningful(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


class QuestionInterpretation(_StrictModel):
    """What FinSight understood the user to be asking.

    ``strategy`` records how the interpretation was produced. In Phase 1 it is
    always ``deterministic_rules``; once an LLM interpreter is wired in it may
    be ``llm``. Either way the interpretation only ever contains catalogued
    metric names and known analysis types.
    """

    restated_question: str
    intent: str = Field(description="A short plain-language summary of the analytical intent.")
    analysis_type: AnalysisType | None = None
    metric: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    strategy: str = "deterministic_rules"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class Explanation(_StrictModel):
    """The narrative layer. Never trusted, always grounded in evidence."""

    summary: str
    detail: str = ""
    findings: list[str] = Field(default_factory=list)
    grounded_on: list[str] = Field(default_factory=list, description="Evidence item IDs cited.")
    provider: str = Field(description="Which component produced the text.")
    model: str | None = None
    generated_at: str | None = None


class Answer(_StrictModel):
    """The structured response to ``POST /questions``."""

    answer_id: str
    status: AnswerStatus
    question: str
    interpretation: QuestionInterpretation
    plan: AnalysisPlan | None = None
    analyses: list[AnalysisResult] = Field(default_factory=list)
    evidence: EvidencePackage = Field(default_factory=EvidencePackage)
    explanation: Explanation | None = None
    caveats: list[str] = Field(default_factory=list)
    llm_enabled: bool = False
    duration_ms: float = 0.0
    created_at: str


class AnswerListResponse(_StrictModel):
    answers: list[str] = Field(default_factory=list)
    total: int