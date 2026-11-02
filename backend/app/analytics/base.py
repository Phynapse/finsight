"""The deterministic analytics abstraction.

Every analyser in FinSight obeys the same contract:

* it receives a validated :class:`AnalysisPlan` and a read-only repository,
* it performs Pandas arithmetic with no language model in the loop,
* it returns a typed :class:`AnalysisResult` whose evidence can be audited.

That is the whole point of the architecture: the numbers are computed in
Python, so the numbers are testable.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

import pandas as pd

from app.core.errors import (
    AnalysisExecutionError,
    InvalidFilterError,
    InvalidPeriodError,
)
from app.data.repository import DatasetRepository
from app.models.catalog import (
    ANALYSIS_TYPE_CATALOG,
    AnalysisTypeSpec,
    MetricSpec,
    resolve_metric,
)
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    ComparisonMode,
    Dimension,
    Direction,
    Unit,
)
from app.schemas.analysis import (
    AnalysisPlan,
    AnalysisResult,
    DimensionValue,
    FinancialMetric,
)

TWO_DP = 2
PERCENT_DP = 2


# ---------------------------------------------------------------------------
# Numeric helpers - the only arithmetic primitives the analysers use
# ---------------------------------------------------------------------------
def safe_percentage(numerator: float, denominator: float) -> float | None:
    """``numerator / denominator`` expressed as a percentage, or ``None``.

    Every percentage in the metric catalog follows ``x / y * 100``. Returning
    ``None`` for a zero denominator keeps a missing base explicit instead of
    inventing a zero or raising.
    """
    if denominator in (0, 0.0) or pd.isna(denominator):
        return None
    return round(numerator / denominator * 100.0, PERCENT_DP)


def safe_average(total: float, count: float) -> float | None:
    """``total / count`` for non-percentage ratios, guarding a zero count."""
    if count in (0, 0.0) or pd.isna(count):
        return None
    return round(total / count, TWO_DP)


def safe_percentage_change(current: float, previous: float) -> float | None:
    """Period-over-period change, guarding the zero and missing base cases."""
    if previous in (0, 0.0) or pd.isna(previous):
        return None
    return round((current - previous) / abs(previous) * 100.0, PERCENT_DP)


def absolute_change(current: float, previous: float) -> float | None:
    if pd.isna(current) or pd.isna(previous):
        return None
    return round(current - previous, TWO_DP)


def direction_of(current: float | None, previous: float | None, tolerance: float = 0.01) -> Direction:
    if current is None or previous is None:
        return Direction.UNKNOWN
    change = current - previous
    if change > tolerance:
        return Direction.INCREASE
    if change < -tolerance:
        return Direction.DECREASE
    return Direction.FLAT


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PeriodPair:
    """The requested period and the period it is compared against."""

    period: str | None
    comparison_period: str | None
    mode: ComparisonMode


def resolve_comparison(plan: AnalysisPlan, repository: DatasetRepository) -> PeriodPair:
    """Resolve the comparison period for a plan.

    An explicit ``comparison_period`` always wins. Otherwise the comparison is
    derived from ``comparison_mode`` against the ordered period list. Asking to
    compare a period that has no predecessor is a validation error, not a
    silent zero.
    """
    known = repository.periods
    period = plan.period

    if plan.comparison_period:
        if plan.comparison_period not in known:
            raise InvalidPeriodError(
                f"Comparison period '{plan.comparison_period}' is not in the dataset.",
                details={"period": plan.comparison_period, "available_periods": known},
            )
        return PeriodPair(period, plan.comparison_period, ComparisonMode.NONE)

    if plan.comparison_mode == ComparisonMode.NONE:
        return PeriodPair(period, None, ComparisonMode.NONE)

    if period is None:
        raise InvalidPeriodError(
            "A comparison mode requires an explicit period.",
            details={"comparison_mode": plan.comparison_mode},
        )
    if period not in known:
        raise InvalidPeriodError(
            f"Period '{period}' is not in the dataset.",
            details={"period": period, "available_periods": known},
        )

    if plan.comparison_mode == ComparisonMode.PRIOR_QUARTER:
        index = known.index(period)
        if index == 0:
            raise InvalidPeriodError(
                f"Period '{period}' is the earliest period in the dataset and has no prior quarter.",
                details={"period": period},
            )
        return PeriodPair(period, known[index - 1], plan.comparison_mode)

    # PRIOR_YEAR: same quarter, previous fiscal year.
    year_text, quarter_text = period.split("-Q")
    prior_year = f"{int(year_text) - 1}-Q{quarter_text}"
    if prior_year not in known:
        raise InvalidPeriodError(
            f"No prior year data for '{period}'.",
            details={"period": period, "expected_comparison_period": prior_year},
        )
    return PeriodPair(period, prior_year, plan.comparison_mode)


def month_range(period: str) -> list[str]:
    """The three month keys belonging to a fiscal quarter key."""
    year_text, quarter_text = period.split("-Q")
    year, quarter = int(year_text), int(quarter_text)
    first_month = (quarter - 1) * 3 + 1
    return [f"{year}-{month:02d}" for month in range(first_month, first_month + 3)]


# ---------------------------------------------------------------------------
# Context and base class
# ---------------------------------------------------------------------------
@dataclass
class AnalysisContext:
    """Everything an analyser is allowed to touch."""

    repository: DatasetRepository
    plan: AnalysisPlan
    spec: AnalysisTypeSpec
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def metric_spec(self, metric_id: str | None = None) -> MetricSpec:
        target = metric_id or self.plan.metric
        spec = resolve_metric(target)
        if spec is None:
            raise AnalysisExecutionError(
                f"Metric '{target}' is not catalogued.", details={"metric": target}
            )
        return spec

    def statement_frame(self) -> pd.DataFrame:
        return self.repository.frame("financial_data")

    def transactions_frame(self) -> pd.DataFrame:
        return self.repository.frame("transactions")

    def budgets_frame(self) -> pd.DataFrame:
        return self.repository.frame("budgets")

    def vendors_frame(self) -> pd.DataFrame:
        return self.repository.frame("vendors")

    def currency(self) -> str:
        return self.repository.currency()


def financial_metric(
    spec: MetricSpec,
    value: float,
    *,
    context: AnalysisContext,
    period: str | None = None,
    comparison: float | None = None,
    comparison_period: str | None = None,
    inputs: dict[str, float] | None = None,
) -> FinancialMetric:
    """Build a typed :class:`FinancialMetric` with its provenance attached.

    Every number that leaves the analytics layer passes through here, which is
    what guarantees each one carries the formula that produced it. When a
    comparison value is supplied the change and percentage change are computed
    here rather than in the caller, so every metric compares the same way.
    """
    currency = context.currency() if spec.unit is Unit.CURRENCY else None
    return FinancialMetric(
        id=spec.id,
        label=spec.label,
        value=round(float(value), TWO_DP),
        unit=spec.unit,
        currency=currency,
        period=period,
        comparison_period=comparison_period,
        comparison_value=None if comparison is None else round(float(comparison), TWO_DP),
        change=None if comparison is None else absolute_change(float(value), float(comparison)),
        percentage_change=(
            None if comparison is None else safe_percentage_change(float(value), float(comparison))
        ),
        source_dataset=spec.source_dataset,
        calculation=spec.formula,
        formula_inputs={key: round(float(item), TWO_DP) for key, item in (inputs or {}).items()},
    )


class Analyzer(ABC):
    """Base class for every deterministic analyser."""

    analysis_type: AnalysisType

    @abstractmethod
    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        """Compute the analysis. Must be free of side effects."""


@dataclass
class AnalyzerOutput:
    """What an analyser hands back before the service wraps it."""

    metrics: list[FinancialMetric] = field(default_factory=list)
    breakdown: list[DimensionValue] = field(default_factory=list)
    series: list[DimensionValue] = field(default_factory=list)
    methodology: list[str] = field(default_factory=list)
    period: str | None = None
    comparison_period: str | None = None
    row_count: int = 0


class AnalyzerRegistry:
    """Maps analysis types onto analyser instances."""

    def __init__(self) -> None:
        self._analyzers: dict[AnalysisType, Analyzer] = {}

    def register(self, analyzer: Analyzer) -> None:
        self._analyzers[analyzer.analysis_type] = analyzer

    def get(self, analysis_type: AnalysisType) -> Analyzer:
        try:
            return self._analyzers[analysis_type]
        except KeyError as error:
            raise AnalysisExecutionError(
                f"No analyser registered for '{analysis_type}'.",
                details={"analysis_type": analysis_type},
            ) from error

    def registered(self) -> tuple[AnalysisType, ...]:
        return tuple(self._analyzers)

    def validate_catalog_coverage(self) -> None:
        """Every catalogued analysis type must have an implementation."""
        missing = set(ANALYSIS_TYPE_CATALOG) - set(self._analyzers)
        if missing:  # pragma: no cover - guarded by tests
            raise AnalysisExecutionError(
                "Catalogued analysis types without an implementation: "
                + ", ".join(sorted(missing))
            )


def build_result(
    *,
    analysis_id: str,
    plan: AnalysisPlan,
    context: AnalysisContext,
    output: AnalyzerOutput,
    datasets_used: Sequence[str],
    duration_ms: float,
) -> AnalysisResult:
    return AnalysisResult(
        analysis_id=analysis_id,
        status=AnalysisStatus.SUCCEEDED,
        analysis_type=plan.analysis_type,
        metric=plan.metric,
        plan=plan,
        period=output.period or plan.period,
        comparison_period=output.comparison_period or plan.comparison_period,
        metrics=output.metrics,
        breakdown=output.breakdown,
        series=output.series,
        methodology=output.methodology,
        warnings=context.warnings,
        row_count=output.row_count,
        duration_ms=duration_ms,
        executed_at=datetime.now(timezone.utc),
        datasets_used=list(datasets_used),
    )


class Timer:
    """Small helper so every analyser reports the same duration metric."""

    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 2)


def new_analysis_id() -> str:
    return f"an_{uuid4().hex[:16]}"


def percent_of_total(value: float, total: float) -> float | None:
    return safe_percentage(value, total)


def make_dimension_value(
    dimension: Dimension,
    key: str,
    value: float,
    *,
    label: str | None = None,
    metric: str | None = None,
    comparison_value: float | None = None,
    total: float | None = None,
    transaction_count: int | None = None,
    total_change: float | None = None,
) -> DimensionValue:
    """Build a breakdown row with its derived comparison fields.

    ``metric`` names the catalogued metric a row represents. It is set whenever
    the row is a component of a wider statement (the revenue row inside a
    profitability breakdown, for example) so the row is not mislabelled with
    the plan's headline metric.
    """
    change = absolute_change(value, comparison_value) if comparison_value is not None else None
    return DimensionValue(
        dimension=dimension,
        key=str(key)[:120],
        label=(label or str(key))[:120],
        metric=metric,
        value=round(float(value), TWO_DP),
        comparison_value=(
            round(float(comparison_value), TWO_DP) if comparison_value is not None else None
        ),
        change=change,
        percentage_change=(
            safe_percentage_change(value, comparison_value)
            if comparison_value is not None
            else None
        ),
        share_of_total_pct=percent_of_total(value, total) if total else None,
        transaction_count=transaction_count,
        contribution_to_change_pct=(
            percent_of_total(change, total_change)
            if change is not None and total_change not in (None, 0.0)
            else None
        ),
    )


def optional_float(value: Any) -> float | None:
    """Coerce a Pandas cell to ``float`` while preserving 'no data' as None.

    Total by design: an unparseable cell yields ``None`` rather than raising
    mid-analysis, so one bad row cannot fail a whole analysis. A caller that
    needs to know the value was present can check the column's null count.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None
    try:
        return round(float(value), TWO_DP)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Shared Pandas helpers
# ---------------------------------------------------------------------------
#: The only columns a ledger analysis is ever allowed to group by.
LEDGER_DIMENSION_COLUMN: dict[Dimension, str] = {
    Dimension.DEPARTMENT: "department",
    Dimension.CATEGORY: "category",
    Dimension.VENDOR: "vendor",
    Dimension.MONTH: "period",
    Dimension.QUARTER: "quarter",
}

#: The budget document groups by a narrower set than the ledger.
BUDGET_DIMENSION_COLUMN: dict[Dimension, str] = {
    Dimension.DEPARTMENT: "department",
    Dimension.CATEGORY: "category",
    Dimension.MONTH: "period",
}


def apply_filters(
    frame: pd.DataFrame,
    plan: AnalysisPlan,
    context: AnalysisContext,
    allowed: Sequence[str],
) -> pd.DataFrame:
    """Apply a plan's equality filters, refusing fields outside the allow-list."""
    allowed_fields = set(allowed)
    filtered = frame
    for plan_filter in plan.filters:
        if plan_filter.field not in allowed_fields:
            raise InvalidFilterError(
                f"Filter field '{plan_filter.field}' is not supported by this analysis.",
                details={"field": plan_filter.field, "allowed": sorted(allowed_fields)},
            )
        if plan_filter.field not in filtered.columns:
            context.warn(f"Filter '{plan_filter.field}' is not present on this dataset.")
            continue
        filtered = filtered[filtered[plan_filter.field].isin(plan_filter.values)]
    return filtered


def ledger_for_period(transactions: pd.DataFrame, months: Sequence[str]) -> pd.DataFrame:
    """Scope the ledger to a set of months and add a signed ``net_amount``.

    Expenses add to spend, credit memos subtract from it.
    """
    from app.data.integrity import net_cash_spend

    scoped = transactions[transactions["period"].isin(list(months))].copy()
    scoped["net_amount"] = net_cash_spend(scoped)
    return scoped


def group_spend(
    frame: pd.DataFrame,
    column: str,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    """Group net spend and line counts by an allow-listed column, largest first."""
    if frame.empty:
        return pd.DataFrame(columns=[column, "net_amount", "line_count"])
    grouped = (
        frame.groupby(column, as_index=False)
        .agg(net_amount=("net_amount", "sum"), line_count=("net_amount", "size"))
        .sort_values(by=["net_amount", column], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
    if limit is not None:
        grouped = grouped.head(limit)
    return grouped


def resolve_month_scope(plan: AnalysisPlan, repository: DatasetRepository) -> list[str]:
    """Resolve the ordered month keys a plan covers.

    ``period`` selects a fiscal quarter; ``period`` plus ``period_end`` selects a
    contiguous range of quarters; neither selects every month available.
    """
    months = list(repository.months)
    if not plan.period:
        return months
    start = month_range(plan.period)[0]
    end = month_range(plan.period_end)[-1] if plan.period_end else month_range(plan.period)[-1]
    if start not in months or end not in months:
        raise InvalidPeriodError(
            "The requested month range is not fully covered by the ledger.",
            details={
                "period_start": start,
                "period_end": end,
                "available_months": months,
            },
        )
    start_index, end_index = months.index(start), months.index(end)
    if end_index < start_index:
        raise InvalidPeriodError(
            "period_end precedes period.",
            details={"period": plan.period, "period_end": plan.period_end},
        )
    return months[start_index : end_index + 1]