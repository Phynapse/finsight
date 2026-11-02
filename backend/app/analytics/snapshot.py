"""Metric snapshot: one metric for one period, optionally grouped."""

from __future__ import annotations

import pandas as pd

from app.analytics.base import (
    financial_metric,
    LEDGER_DIMENSION_COLUMN,
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    apply_filters,
    group_spend,
    ledger_for_period,
    make_dimension_value,
    resolve_comparison,
)
from app.core.errors import NoDataForPlanError
from app.models.catalog import resolve_metric
from app.models.enums import AnalysisType, Dimension

STATEMENT_METRICS = (
    "revenue",
    "cogs",
    "gross_profit",
    "operating_expenses",
    "cash_operating_expenses",
    "non_cash_operating_expenses",
    "operating_income",
    "cash_balance",
    "operating_cash_flow",
)

DERIVED_METRICS: dict[str, tuple[str, str]] = {
    "gross_margin_pct": ("gross_profit", "revenue"),
    "operating_margin_pct": ("operating_income", "revenue"),
}


class MetricSnapshotAnalyzer(Analyzer):
    """Report one catalogued metric, with an optional dimensional breakdown."""

    analysis_type = AnalysisType.METRIC_SNAPSHOT

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        periods = resolve_comparison(plan, context.repository)
        spec = context.metric_spec()

        if spec.id in STATEMENT_METRICS:
            value, inputs, sources = self._from_statement(spec.id, context, periods.period)
            comparison_value = (
                self._from_statement(spec.id, context, periods.comparison_period)[0]
                if periods.comparison_period
                else None
            )
            breakdown: list = []
            methodology = [spec.formula]
        elif spec.id in DERIVED_METRICS:
            numerator, denominator = DERIVED_METRICS[spec.id]
            value, inputs, sources = self._derived_margin(spec.id, context, periods.period)
            comparison_value = (
                self._derived_margin(spec.id, context, periods.comparison_period)[0]
                if periods.comparison_period
                else None
            )
            breakdown = []
            methodology = [spec.formula]
        elif spec.source_dataset == "transactions":
            value, comparison_value, breakdown, methodology = self._from_ledger(spec.id, context, periods)
        elif spec.source_dataset == "budgets":
            value, comparison_value, breakdown, methodology = self._from_budgets(spec.id, context, periods)
        else:
            value, comparison_value, breakdown, methodology = self._from_vendors(spec.id, context)

        metrics = [financial_metric(spec, value, context=context, period=periods.period, inputs=inputs)]
        if comparison_value is not None:
            from app.analytics.base import make_dimension_value as _row

            breakdown = [
                _row(
                    Dimension.QUARTER,
                    periods.period or "unknown",
                    value,
                    label=f"{spec.label} {periods.period}",
                    comparison_value=comparison_value,
                ),
                *breakdown,
            ]

        return AnalyzerOutput(
            metrics=metrics,
            breakdown=breakdown,
            methodology=methodology,
            period=periods.period,
            comparison_period=periods.comparison_period,
            row_count=len(breakdown),
        )

    # -- sources -------------------------------------------------------------
    @staticmethod
    def _statement_row(context: AnalysisContext, period: str | None) -> pd.Series | None:
        if period is None:
            return None
        statement = context.statement_frame()
        rows = statement[statement["period"] == period]
        return None if rows.empty else rows.iloc[0]

    def _from_statement(
        self, metric_id: str, context: AnalysisContext, period: str | None
    ) -> tuple[float, dict[str, float], tuple[str, ...]]:
        row = self._statement_row(context, period)
        if row is None:
            raise NoDataForPlanError(
                "No income statement row for the requested period.",
                details={"metric": metric_id, "period": period},
            )
        inputs: dict[str, float] = {}
        if metric_id == "gross_profit":
            inputs = {"revenue": float(row["revenue"]), "cogs": float(row["cogs"])}
            value = round(float(row["revenue"]) - float(row["cogs"]), 2)
        else:
            value = round(float(row[metric_id]), 2)
        return value, inputs, ("financial_data",)

    def _derived_margin(
        self, metric_id: str, context: AnalysisContext, period: str | None
    ) -> tuple[float, dict[str, float], tuple[str, ...]]:
        row = self._statement_row(context, period)
        if row is None:
            raise NoDataForPlanError(
                "No income statement row for the requested period.",
                details={"metric": metric_id, "period": period},
            )
        numerator, denominator = DERIVED_METRICS[metric_id]
        base = float(row[numerator])
        denominator_value = float(row[denominator])
        value = 0.0 if denominator_value == 0 else round(base / denominator_value * 100, 2)
        return value, {numerator: base, denominator: denominator_value}, ("financial_data",)

    def _from_ledger(
        self, metric_id: str, context: AnalysisContext, periods
    ) -> tuple[float, float | None, list, list[str]]:
        from app.analytics.base import month_range

        transactions = apply_filters(
            context.transactions_frame(), context.plan, context, ("department", "category", "vendor_id")
        )
        months = month_range(periods.period) if periods.period else context.repository.months
        scoped = ledger_for_period(transactions, months)

        if metric_id == "total_expense":
            value = round(float(scoped["net_amount"].sum()), 2)
        elif metric_id == "credit_amount":
            value = round(
                float(scoped[scoped["transaction_type"] == "credit"]["amount"].sum()), 2
            )
        else:
            value = float(len(scoped))

        comparison_value = None
        if periods.comparison_period:
            comparison_months = month_range(periods.comparison_period)
            comparison_scoped = ledger_for_period(transactions, comparison_months)
            if metric_id == "total_expense":
                comparison_value = round(float(comparison_scoped["net_amount"].sum()), 2)
            elif metric_id == "credit_amount":
                comparison_value = round(
                    float(
                        comparison_scoped[comparison_scoped["transaction_type"] == "credit"][
                            "amount"
                        ].sum()
                    ),
                    2,
                )
            else:
                comparison_value = float(len(comparison_scoped))

        breakdown: list = []
        if context.plan.dimensions:
            dimension = context.plan.dimensions[0]
            column = LEDGER_DIMENSION_COLUMN[dimension]
            grouped = group_spend(scoped, column)
            total = round(float(grouped["net_amount"].sum()), 2)
            breakdown = [
                make_dimension_value(
                    dimension,
                    str(record[column]),
                    float(record["net_amount"]),
                    total=total,
                    transaction_count=int(record["line_count"]),
                )
                for record in grouped.to_dict(orient="records")
            ]
        return value, comparison_value, breakdown, [
            "ledger net spend = sum(expense amounts) - sum(credit amounts)",
            f"scoped to {len(months)} month(s)",
        ]

    def _from_budgets(self, metric_id: str, context: AnalysisContext, periods) -> tuple[float, float | None, list, list[str]]:
        from app.analytics.base import resolve_month_scope

        budgets = apply_filters(context.budgets_frame(), context.plan, context, ("department", "category"))
        months = resolve_month_scope(context.plan, context.repository)
        scoped = budgets[budgets["period"].isin(months)]
        if scoped.empty:
            raise NoDataForPlanError(
                "No budget lines match this plan.", details={"months": months}
            )
        budget_total = round(float(scoped["budget_amount"].sum()), 2)
        actual_total = round(float(scoped["actual_amount"].sum()), 2)
        value = {"budget_amount": budget_total, "budget_variance": round(actual_total - budget_total, 2)}[metric_id]
        if metric_id == "budget_utilisation_pct":
            value = 0.0 if budget_total == 0 else round(actual_total / budget_total * 100, 2)

        breakdown: list = []
        if context.plan.dimensions:
            dimension = context.plan.dimensions[0]
            column = {
                Dimension.DEPARTMENT: "department",
                Dimension.CATEGORY: "category",
                Dimension.MONTH: "period",
            }.get(dimension, "category")
            grouped = (
                scoped.groupby(column, as_index=False)
                .agg(budget=("budget_amount", "sum"), actual=("actual_amount", "sum"))
                .reset_index(drop=True)
            )
            variance_total = round(float(grouped["actual"].sum() - grouped["budget"].sum()), 2)
            breakdown = [
                make_dimension_value(
                    dimension,
                    str(record[column]),
                    round(float(record["actual"]) - float(record["budget"]), 2),
                    total=variance_total or None,
                )
                for record in grouped.to_dict(orient="records")
            ]
        return value, None, breakdown, [
            "variance = actual_amount - budget_amount (positive is overspend)",
            f"scope: {len(scoped)} budget lines across {len(months)} month(s)",
        ]

    def _from_vendors(self, metric_id: str, context: AnalysisContext) -> tuple[float, float | None, list, list[str]]:
        vendors = context.vendors_frame()
        total = round(float(vendors["total_spend_2024"].sum()), 2)
        if metric_id == "vendor_count":
            value = float(vendors["vendor_id"].nunique())
        elif metric_id == "top_vendor_spend":
            value = round(float(vendors["total_spend_2024"].max()), 2)
        else:
            top_five = round(float(vendors["total_spend_2024"].nlargest(5).sum()), 2)
            value = 0.0 if total == 0 else round(top_five / total * 100, 2)

        breakdown: list = []
        if context.plan.dimensions and context.plan.dimensions[0] is Dimension.VENDOR:
            breakdown = [
                make_dimension_value(
                    Dimension.VENDOR,
                    str(record["vendor_id"]),
                    round(float(record["total_spend_2024"]), 2),
                    label=str(record["vendor_name"]),
                    total=total,
                    transaction_count=int(record["transaction_count_2024"]),
                )
                for record in vendors.sort_values("total_spend_2024", ascending=False)
                .to_dict(orient="records")
            ]
        return value, None, breakdown, [
            "vendor spend is the declared FY2024 roll-up, asserted against the ledger at startup",
            f"{len(vendors)} supplier relationships registered",
        ]
