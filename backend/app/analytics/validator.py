"""Analysis plan validation.

The validator is the security boundary of the analytics layer. A plan arrives
either from an HTTP client or, in a later phase, from a language model. In both
cases it is checked here against the catalog before any Pandas code runs:

* the analysis type must exist,
* the metric must exist and be supported by that analysis type,
* the metric's source dataset must be loaded,
* the period and comparison period must exist in the data,
* every dimension must be on the analysis type's allow-list,
* every filter field must be on the analysis type's allow-list and must exist
  in the source dataset.

Everything is collected before raising, so a caller sees every problem at once.
"""

from __future__ import annotations

from app.core.errors import (
    InvalidFilterError,
    InvalidPeriodError,
    PlanValidationError,
    UnknownAnalysisTypeError,
    UnknownMetricError,
)
from app.data.repository import DatasetRepository
from app.models.catalog import (
    resolve_analysis_type,
    resolve_dataset,
    resolve_metric,
)
from app.schemas.analysis import AnalysisPlan


class PlanValidator:
    """Validates an :class:`AnalysisPlan` against the catalog and the data."""

    def __init__(self, repository: DatasetRepository) -> None:
        self.repository = repository

    def validate(self, plan: AnalysisPlan) -> None:
        """Raise :class:`PlanValidationError` listing every problem found."""
        problems: list[dict[str, str]] = []

        spec = resolve_analysis_type(plan.analysis_type)
        if spec is None:
            raise UnknownAnalysisTypeError(
                f"Analysis type '{plan.analysis_type}' is not supported.",
                details={"analysis_type": str(plan.analysis_type)},
            )

        metric = resolve_metric(plan.metric)
        if metric is None:
            raise UnknownMetricError(
                f"Metric '{plan.metric}' is not defined in the metric catalog.",
                details={"metric": plan.metric},
            )
        if not spec.supports_metric(metric.id):
            problems.append(
                {
                    "field": "metric",
                    "message": (
                        f"Analysis '{spec.id}' does not support metric '{metric.id}'."
                    ),
                }
            )

        for dataset_id in spec.required_datasets:
            dataset = resolve_dataset(dataset_id)
            if dataset is None:
                problems.append(
                    {
                        "field": "required_datasets",
                        "message": f"Unknown dataset '{dataset_id}'.",
                    }
                )
            elif not self.repository.has(dataset_id):
                problems.append(
                    {
                        "field": "required_datasets",
                        "message": f"Dataset '{dataset_id}' is not loaded.",
                    }
                )

        if metric.source_dataset and not self.repository.has(metric.source_dataset):
            problems.append(
                {
                    "field": "metric",
                    "message": f"Source dataset '{metric.source_dataset}' is not loaded.",
                }
            )

        problems.extend(self._validate_periods(plan))
        problems.extend(self._validate_dimensions(plan, spec))
        problems.extend(self._validate_filters(plan, spec))

        if plan.comparison_mode.value != "none" and not (
            plan.comparison_period or plan.period
        ):
            problems.append(
                {
                    "field": "comparison_mode",
                    "message": "comparison_mode requires an explicit period.",
                }
            )

        if problems:
            raise PlanValidationError(
                "The analysis plan is not valid.",
                details={"problems": problems, "analysis_type": str(spec.id)},
            )

    # -- individual checks --------------------------------------------------
    def _validate_periods(self, plan: AnalysisPlan) -> list[dict[str, str]]:
        problems: list[dict[str, str]] = []
        known = set(self.repository.periods)

        for field_name in ("period", "period_end", "comparison_period"):
            value = getattr(plan, field_name)
            if value is not None and value not in known:
                problems.append(
                    {
                        "field": field_name,
                        "message": (
                            f"Period '{value}' is not present in the dataset."
                        ),
                    }
                )

        if plan.period and plan.period_end and plan.period not in known:
            pass  # already reported
        elif plan.period and plan.period_end and known:
            if self.repository.periods.index(plan.period_end) < self.repository.periods.index(plan.period):
                problems.append(
                    {
                        "field": "period_end",
                        "message": "period_end precedes period.",
                    }
                )

        if plan.period is not None and plan.period == plan.comparison_period:
            problems.append(
                {
                    "field": "comparison_period",
                    "message": "A period cannot be compared against itself.",
                }
            )
        return problems

    def _validate_dimensions(self, plan: AnalysisPlan, spec) -> list[dict[str, str]]:
        problems: list[dict[str, str]] = []
        for dimension in plan.dimensions:
            if not spec.supports_dimension(dimension):
                problems.append(
                    {
                        "field": "dimensions",
                        "message": (
                            f"Analysis '{spec.id}' does not support the '{dimension}' dimension."
                        ),
                    }
                )
        return problems

    def _validate_filters(self, plan: AnalysisPlan, spec) -> list[dict[str, str]]:
        problems: list[dict[str, str]] = []
        for plan_filter in plan.filters:
            if not spec.supports_filter(plan_filter.field):
                problems.append(
                    {
                        "field": "filters",
                        "message": (
                            f"Analysis '{spec.id}' does not support filtering on "
                            f"'{plan_filter.field}'."
                        ),
                    }
                )
                continue
            if not self._filter_field_exists(plan_filter.field):
                problems.append(
                    {
                        "field": "filters",
                        "message": (
                            f"Filter field '{plan_filter.field}' does not exist in the "
                            "loaded datasets."
                        ),
                    }
                )
        return problems

    def _filter_field_exists(self, field_name: str) -> bool:
        for dataset_id in self.repository.datasets:
            if field_name in self.repository.snapshot(dataset_id).frame.columns:
                return True
        return False

    # -- convenience --------------------------------------------------------
    def validate_or_raise_filter(self, plan: AnalysisPlan, field_name: str) -> None:
        """Defensive helper for analysers that build their own filters."""
        spec = resolve_analysis_type(plan.analysis_type)
        if spec is None or not spec.supports_filter(field_name):
            raise InvalidFilterError(
                f"Filter field '{field_name}' is not supported.",
                details={"field": field_name},
            )


def default_period(repository: DatasetRepository) -> str:
    return repository.latest_period


def assert_period_exists(repository: DatasetRepository, period: str) -> None:
    if period not in repository.periods:
        raise InvalidPeriodError(
            f"Period '{period}' is not in the dataset.",
            details={"period": period, "available_periods": repository.periods},
        )