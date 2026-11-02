"""Evidence contracts.

``EvidenceItem`` is the boundary between deterministic computation and
language. Every number an explanation is allowed to mention must first exist
here, produced by Python/Pandas, carrying its source dataset and its formula.
"""

from __future__ import annotations

from pydantic import Field

from app.models.enums import Direction, Unit
from app.schemas.analysis import DimensionValue, _StrictModel


class EvidenceItem(_StrictModel):
    """One auditable financial fact.

    ``value`` is what the data says. ``comparison_value``, ``change`` and
    ``percentage_change`` describe the movement against the comparison period.
    ``calculation`` states the formula, so a reader can reproduce the number
    without trusting the model that narrated it.
    """

    id: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=160)
    value: float
    unit: Unit
    currency: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    comparison_value: float | None = None
    change: float | None = None
    percentage_change: float | None = None
    direction: Direction = Direction.UNKNOWN
    share_of_total_pct: float | None = None
    contribution_to_change_pct: float | None = None
    source_dataset: str = Field(min_length=1, max_length=64)
    source_fields: list[str] = Field(default_factory=list)
    calculation: str = Field(min_length=1, max_length=500)
    is_derived: bool = Field(
        default=True,
        description="False when the value is read straight from a source dataset column.",
    )


class EvidencePackage(_StrictModel):
    """The complete, bounded set of facts backing one answer."""

    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=200)
    datasets_used: list[str] = Field(default_factory=list)
    periods_covered: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.evidence

    def by_metric(self, metric: str) -> list[EvidenceItem]:
        return [item for item in self.evidence if item.metric == metric]

    def evidence_ids(self) -> list[str]:
        return [item.id for item in self.evidence]


class BreakdownEvidence(_StrictModel):
    """Pairs an evidence item with the rows that make up a breakdown."""

    evidence: EvidenceItem
    rows: list[DimensionValue] = Field(default_factory=list)