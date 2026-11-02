"""Revenue performance analysis."""

from __future__ import annotations

import pandas as pd

from app.analytics.base import (
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    financial_metric,
    make_dimension_value,
    optional_float,
    resolve_comparison,
    safe_percentage,
)
from app.core.errors import InvalidPeriodError, NoDataForPlanError
from app.models.catalog import resolve_metric
from app.models.enums import AnalysisType, Dimension


class RevenueAnalyzer(Analyzer):
    """Revenue, cost of goods sold, gross profit and gross margin.

    Every value is read from the income statement; margins are recomputed from
    the underlying columns rather than trusted from the file.
    """

    analysis_type = AnalysisType.REVENUE_PERFORMANCE

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        periods = resolve_comparison(plan, context.repository)
        if periods.period is None:
            raise InvalidPeriodError("A period is required for revenue performance.")

        statement = context.statement_frame().set_index("period", drop=False)
        current_row = self._row(statement, periods.period)
        comparison_row = (
            self._row(statement, periods.comparison_period)
            if periods.comparison_period
            else None
        )

        revenue = float(current_row["revenue"])
        cogs = float(current_row["cogs"])
        gross_profit = round(revenue - cogs, 2)
        margin = safe_percentage(gross_profit, revenue)
        previous_revenue = float(comparison_row["revenue"]) if comparison_row is not None else None
        previous_cogs = float(comparison_row["cogs"]) if comparison_row is not None else None
        previous_gross = (
            round(previous_revenue - previous_cogs, 2)
            if previous_revenue is not None and previous_cogs is not None
            else None
        )
        previous_margin = (
            safe_percentage(previous_gross, previous_revenue)
            if previous_gross is not None and previous_revenue is not None
            else None
        )

        metrics = [
            financial_metric(
                resolve_metric("revenue"),
                revenue,
                context=context,
                period=periods.period,
                comparison=previous_revenue,
                comparison_period=periods.comparison_period,
            ),
            financial_metric(
                resolve_metric("cogs"),
                cogs,
                context=context,
                period=periods.period,
                comparison=previous_cogs,
                comparison_period=periods.comparison_period,
                inputs={"revenue": revenue},
            ),
            financial_metric(
                resolve_metric("gross_profit"),
                gross_profit,
                context=context,
                period=periods.period,
                comparison=previous_gross,
                comparison_period=periods.comparison_period,
                inputs={"revenue": revenue, "cogs": cogs},
            ),
        ]
        if margin is not None:
            metrics.append(
                financial_metric(
                    resolve_metric("gross_margin_pct"),
                    margin,
                    context=context,
                    period=periods.period,
                    comparison=previous_margin,
                    comparison_period=periods.comparison_period,
                    inputs={"gross_profit": gross_profit, "revenue": revenue},
                )
            )

        breakdown: list = []
        if comparison_row is not None:
            breakdown = [
                make_dimension_value(
                    Dimension.QUARTER,
                    periods.period or "unknown",
                    revenue,
                    label=f"Revenue {periods.period}",
                    metric="revenue",
                    comparison_value=previous_revenue,
                    total=revenue,
                ),
                make_dimension_value(
                    Dimension.QUARTER,
                    periods.period or "unknown",
                    gross_profit,
                    label=f"Gross profit {periods.period}",
                    metric="gross_profit",
                    comparison_value=previous_gross,
                    total=gross_profit,
                ),
            ]
            if margin is not None and previous_margin is not None:
                breakdown.append(
                    make_dimension_value(
                        Dimension.QUARTER,
                        periods.period or "unknown",
                        margin,
                        label=f"Gross margin {periods.period}",
                        metric="gross_margin_pct",
                        comparison_value=previous_margin,
                    )
                )

        return AnalyzerOutput(
            metrics=metrics,
            breakdown=breakdown,
            methodology=[
                "gross_profit = revenue - cogs (recomputed, not read from the file)",
                "gross_margin_pct = gross_profit / revenue * 100",
                "comparison values are read from the comparison period's own row",
            ],
            period=periods.period,
            comparison_period=periods.comparison_period,
            row_count=1 + (1 if comparison_row is not None else 0),
        )

    @staticmethod
    def _row(statement: pd.DataFrame, period: str | None) -> pd.Series:
        if period is None:
            raise InvalidPeriodError("A period is required for this analysis.")
        rows = statement[statement["period"] == period]
        if rows.empty:
            raise InvalidPeriodError(
                f"Period '{period}' is not in the income statement.",
                details={"period": period},
            )
        return rows.iloc[0]


def summarise_period(statement: pd.DataFrame, period: str) -> dict[str, float]:
    """Small helper reused by the profitability analyser."""
    rows = statement[statement["period"] == period]
    if rows.empty:  # pragma: no cover - guarded by the plan validator
        raise NoDataForPlanError(
            f"No income statement row for period '{period}'.", details={"period": period}
        )
    row = rows.iloc[0]
    return {
        "revenue": optional_float(row["revenue"]) or 0.0,
        "cogs": optional_float(row["cogs"]) or 0.0,
        "gross_profit": optional_float(row["gross_profit"]) or 0.0,
        "operating_expenses": optional_float(row["operating_expenses"]) or 0.0,
        "operating_income": optional_float(row["operating_income"]) or 0.0,
        "cash_balance": optional_float(row["cash_balance"]) or 0.0,
    }
