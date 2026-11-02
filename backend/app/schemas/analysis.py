"""Analysis request, plan and result contracts.

``AnalysisPlan`` is the contract between the (future) language model and the
deterministic analytics layer. It is a closed structure with an allow-list, and
it is validated against the metric / dataset / analysis-type catalog before any
Pandas code runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    ComparisonMode,
    Dimension,
    Granularity,
    Unit,
)

_PERIOD_PATTERN = r"^\d{4}-Q[1-4]$"
_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

PeriodKey = Annotated[str, Field(pattern=_PERIOD_PATTERN, description="Fiscal quarter key.")]
MonthKey = Annotated[str, Field(pattern=_MONTH_PATTERN, description="Calendar month key.")]


class _StrictModel(BaseModel):
    """Base for every transport contract: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class AnalysisFilter(_StrictModel):
    """A single equality filter. Field names are validated against an allow-list."""

    field: str = Field(min_length=1, max_length=40)
    values: list[str] = Field(min_length=1, max_length=25)
    operator: str = Field(default="in", pattern="^(in|eq|equals)$")

    @field_validator("values")
    @classmethod
    def values_must_be_clean(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 120 for value in cleaned):
            raise ValueError("filter values must be non-empty and at most 120 characters")
        return cleaned


class AnalysisPlan(_StrictModel):
    """A validated, deterministic description of the analysis to run.

    This object is deliberately boring: an analysis type, a catalogued metric,
    allow-listed dimensions, a period, an optional comparison, and allow-listed
    equality filters. There is no free-form expression, no query language and
    no code path of any kind.
    """

    analysis_type: AnalysisType
    metric: str = Field(min_length=1, max_length=64)
    period: str | None = Field(default=None, pattern=_PERIOD_PATTERN)
    period_end: str | None = Field(default=None, pattern=_PERIOD_PATTERN)
    comparison_period: str | None = Field(default=None, pattern=_PERIOD_PATTERN)
    comparison_mode: ComparisonMode = ComparisonMode.NONE
    dimensions: list[Dimension] = Field(default_factory=list, max_length=3)
    filters: list[AnalysisFilter] = Field(default_factory=list, max_length=5)
    granularity: Granularity | None = None
    limit: int = Field(default=10, ge=1, le=25)

    @field_validator("dimensions")
    @classmethod
    def dimensions_must_be_unique(cls, dimensions: list[Dimension]) -> list[Dimension]:
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("dimensions must be unique")
        return dimensions


class AnalysisRequest(_StrictModel):
    """Body of ``POST /analysis``.

    Callers submit a plan; the service validates it against the catalog and
    executes the matching analyser.
    """

    plan: AnalysisPlan
    question: str | None = Field(default=None, max_length=500)
    persist: bool = Field(default=True, description="Store the result for later retrieval.")


class FinancialMetric(_StrictModel):
    """A single computed metric value with its provenance.

    The comparison fields are populated whenever the plan resolved a comparison
    period, so the headline number of an analysis always carries its own
    movement rather than requiring the reader to join it up from a breakdown.
    """

    id: str
    label: str
    value: float
    unit: Unit
    currency: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    comparison_value: float | None = None
    change: float | None = None
    percentage_change: float | None = None
    source_dataset: str
    calculation: str = Field(description="The exact formula used to produce this value.")
    formula_inputs: dict[str, float] = Field(default_factory=dict)


class DimensionValue(_StrictModel):
    """One row of a dimensional breakdown or one point of a time series."""

    dimension: Dimension
    key: str = Field(max_length=120)
    label: str = Field(max_length=120)
    metric: str | None = Field(
        default=None,
        max_length=64,
        description="Catalogued metric this row measures, when it is not the plan's headline metric.",
    )
    value: float
    comparison_value: float | None = None
    change: float | None = None
    percentage_change: float | None = None
    share_of_total_pct: float | None = None
    transaction_count: int | None = None
    contribution_to_change_pct: float | None = None


class AnalysisResult(_StrictModel):
    """The outcome of one deterministic analysis."""

    analysis_id: str
    status: AnalysisStatus
    analysis_type: AnalysisType
    metric: str
    plan: AnalysisPlan
    period: str | None = None
    comparison_period: str | None = None
    metrics: list[FinancialMetric] = Field(default_factory=list)
    breakdown: list[DimensionValue] = Field(default_factory=list)
    series: list[DimensionValue] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    row_count: int = 0
    duration_ms: float = 0.0
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    datasets_used: list[str] = Field(default_factory=list)

    def serialise(self) -> dict[str, Any]:
        return self.model_dump(mode="json")