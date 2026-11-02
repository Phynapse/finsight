"""Trend analysis: an ordered series with period-over-period growth."""

from __future__ import annotations

import pandas as pd

from app.analytics.base import (
    financial_metric,
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    apply_filters,
    ledger_for_period,
    make_dimension_value,
    safe_percentage_change,
)
from app.core.errors import NoDataForPlanError
from app.models.catalog import MetricSpec, resolve_metric
from app.models.enums import AnalysisType, Dimension

# Metrics that live in the income statement, and their source column.
STATEMENT_COLUMN: dict[str, str] = {
    "revenue": "revenue",
    "cogs": "cogs",
    "gross_profit": "gross_profit",
    "operating_expenses": "operating_expenses",
    "cash_operating_expenses": "cash_operating_expenses",
    "non_cash_operating_expenses": "non_cash_operating_expenses",
    "operating_income": "operating_income",
    "cash_balance": "cash_balance",
    "operating_cash_flow": "cash_operating_cash_flow",
}

# Metrics that must be derived rather than read, with their formula inputs.
DERIVED_STATEMENT: dict[str, tuple[tuple[str, ...], str]] = {
    "gross_margin_pct": (("gross_profit", "revenue"), "gross_margin_pct = gross_profit / revenue * 100"),
    "operating_margin_pct": (
        ("operating_income", "revenue"),
        "operating_margin_pct = operating_income / revenue * 100",
    ),
}

# Metrics derived from the transaction ledger.
LEDGER_METRICS = ("total_expense", "credit_amount", "transaction_count")


class TrendAnalyzer(Analyzer):
    """An ordered series for a metric across the periods present in the data."""

    analysis_type = AnalysisType.TREND

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        spec = context.metric_spec()
        frame = self._series_frame(spec, context)
        if frame.empty:
            raise NoDataForPlanError(
                "No data available for this metric.",
                details={"metric": spec.id, "source_dataset": spec.source_dataset},
            )

        granularity = (plan.granularity.value if plan.granularity else self._default_granularity(spec))
        dimension = Dimension.MONTH if granularity == "month" else Dimension.QUARTER

        rows: list = []
        previous_value: float | None = None
        for record in frame.itertuples(index=False):
            value = round(float(getattr(record, "value")), 2)
            rows.append(
                make_dimension_value(
                    dimension,
                    str(record.period),
                    value,
                    label=f"{spec.label} {record.period}",
                    metric=spec.id,
                    comparison_value=previous_value,
                )
            )
            previous_value = value

        first, last = rows[0].value, rows[-1].value
        first_period = str(frame.iloc[0]["period"])
        last_period = str(frame.iloc[-1]["period"])
        overall = safe_percentage_change(last, first)
        metrics = [
            financial_metric(
                spec,
                last,
                context=context,
                period=last_period,
                comparison=first,
                comparison_period=first_period,
                inputs={"first_value": first, "last_value": last},
            )
        ]

        direction = "increasing" if overall is not None and overall > 0 else "flat or decreasing"
        return AnalyzerOutput(
            metrics=metrics,
            series=rows,
            breakdown=rows[-plan.limit :],
            methodology=[
                spec.formula,
                f"periods ordered oldest to newest; {len(rows)} point(s)",
                f"first {first:,.2f} to last {last:,.2f} ({overall:.2f}% change)"
                if overall is not None
                else "overall change not computable (zero base)",
                f"observed direction: {direction}",
            ],
            period=plan.period,
            comparison_period=plan.comparison_period,
            row_count=len(rows),
        )

    # -- series construction -------------------------------------------------
    def _series_frame(self, spec: MetricSpec, context: AnalysisContext) -> pd.DataFrame:
        if spec.id in STATEMENT_COLUMN:
            statement = context.statement_frame()
            if plan_filters_present(context):
                statement = apply_filters(
                    statement, context.plan, context, ("department", "category")
                )
            column = STATEMENT_COLUMN[spec.id]
            frame = statement[["period", column]].rename(columns={column: "value"})
            return frame.sort_values("period").reset_index(drop=True)

        if spec.id in DERIVED_STATEMENT:
            inputs, _formula = DERIVED_STATEMENT[spec.id]
            statement = context.statement_frame()
            numerator, denominator = inputs
            frame = statement[["period", numerator, denominator]].copy()
            frame["value"] = (frame[numerator] / frame[denominator] * 100).round(2)
            frame = frame[["period", "value"]]
            return frame.sort_values("period").reset_index(drop=True)

        if spec.id in LEDGER_METRICS:
            transactions = apply_filters(
                context.transactions_frame(),
                context.plan,
                context,
                ("department", "category", "is_non_cash", "transaction_type"),
            )
            scoped = ledger_for_period(transactions, context.repository.months)
            if spec.id == "total_expense":
                frame = (
                    scoped.groupby("period", as_index=False)["net_amount"]
                    .sum()
                    .rename(columns={"net_amount": "value"})
                )
            elif spec.id == "credit_amount":
                credits = scoped[scoped["transaction_type"] == "credit"]
                frame = (
                    credits.groupby("period", as_index=False)["amount"]
                    .sum()
                    .rename(columns={"amount": "value"})
                )
            else:
                frame = (
                    scoped.groupby("period", as_index=False)["net_amount"]
                    .size()
                    .rename(columns={"net_amount": "value"})
                )
            frame["value"] = frame["value"].round(2)
            return frame.sort_values("period").reset_index(drop=True)

        # Remaining metrics (budgets and vendors) are summarised by period.
        if spec.source_dataset == "budgets":
            budgets = apply_filters(
                context.budgets_frame(), context.plan, context, ("department", "category")
            )
            frame = (
                budgets.groupby("period", as_index=False)["budget_amount"]
                .sum()
                .rename(columns={"budget_amount": "value"})
            )
            frame["value"] = frame["value"].round(2)
            return frame.sort_values("period").reset_index(drop=True)

        vendors = context.vendors_frame()
        frame = pd.DataFrame(
            {
                "period": [f"{context.repository.latest_period}"],
                "value": [round(float(vendors["total_spend_2024"].max()), 2)],
            }
        )
        return frame

    @staticmethod
    def _default_granularity(spec: MetricSpec) -> str:
        if spec.source_dataset in {"financial_data", "budgets"}:
            return "quarter" if spec.source_dataset == "financial_data" else "month"
        if spec.id in LEDGER_METRICS:
            return "month"
        return "quarter"


def plan_filters_present(context: AnalysisContext) -> bool:
    return bool(context.plan.filters)
