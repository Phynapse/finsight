"""Dataset discovery contracts."""

from __future__ import annotations

from pydantic import Field

from app.schemas.analysis import _StrictModel
from app.schemas.dataset import DATASET_ROW_MODELS


class ColumnSchema(_StrictModel):
    """Column-level metadata for one dataset."""

    name: str
    dtype: str
    nullable: bool
    description: str = ""


class DatasetSummary(_StrictModel):
    """Metadata and headline figures for one bundled dataset."""

    id: str
    label: str
    description: str
    grain: str
    row_grain_label: str
    primary_key: list[str]
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    columns: list[ColumnSchema] = Field(default_factory=list)
    period_start: str | None = None
    period_end: str | None = None
    period_count: int = 0
    available_periods: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    integrity_checks: list["IntegrityCheck"] = Field(default_factory=list)


class IntegrityCheck(_StrictModel):
    """The outcome of one cross-dataset consistency assertion."""

    id: str
    description: str
    passed: bool
    datasets: list[str] = Field(default_factory=list)
    observed: str | None = None
    expected: str | None = None
    severity: str = "blocking"


class DatasetListResponse(_StrictModel):
    datasets: list[DatasetSummary]
    total: int


DatasetSummary.model_rebuild()