"""Profitability analysis: the full walk from revenue to operating income."""

from __future__ import annotations

from app.analytics.base import (
    financial_metric,
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    make_dimension_value,
    resolve_comparison,
    safe_average,
    safe_percentage,
)
from app.analytics.revenue import summarise_period
from app.models.catalog import resolve_metric
from app.models.enums import AnalysisType, Dimension

WALK = (
    ("revenue", "Revenue", 1),
    ("cogs", "Cost of goods sold", -1),
    ("gross_profit", "Gross profit", 0),
    ("operating_expenses", "Operating expenses", -1),
    ("operating_income", "Operating income", 0),
)


class ProfitabilityAnalyzer(Analyzer):
    """Revenue to operating income, with margin analysis.

    Margins are always recomputed from the statement columns, so a corrupted
    file could not make FinSight report a margin that does not follow from its
    own revenue and cost figures.
    """

    analysis_type = AnalysisType.PROFITABILITY

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        periods = resolve_comparison(plan, context.repository)
        if periods.period is None:
            from app.core.errors import InvalidPeriodError

            raise InvalidPeriodError("A period is required for profitability analysis.")

        statement = context.statement_frame()
        current = summarise_period(statement, periods.period)
        comparison = (
            summarise_period(statement, periods.comparison_period)
            if periods.comparison_period
            else None
        )

        gross_margin = safe_percentage(current["gross_profit"], current["revenue"])
        operating_margin = safe_percentage(current["operating_income"], current["revenue"])
        previous = comparison or {}
        comparison_period = periods.comparison_period

        def prior(key: str) -> float | None:
            return previous.get(key)

        metrics = [
            financial_metric(
                resolve_metric("revenue"),
                current["revenue"],
                context=context,
                period=periods.period,
                comparison=prior("revenue"),
                comparison_period=comparison_period,
            ),
            financial_metric(
                resolve_metric("cogs"),
                current["cogs"],
                context=context,
                period=periods.period,
                comparison=prior("cogs"),
                comparison_period=comparison_period,
            ),
            financial_metric(
                resolve_metric("gross_profit"),
                current["gross_profit"],
                context=context,
                period=periods.period,
                comparison=prior("gross_profit"),
                comparison_period=comparison_period,
                inputs={
                    "revenue": current["revenue"],
                    "cogs": current["cogs"],
                },
            ),
            financial_metric(
                resolve_metric("operating_expenses"),
                current["operating_expenses"],
                context=context,
                period=periods.period,
                comparison=prior("operating_expenses"),
                comparison_period=comparison_period,
            ),
            financial_metric(
                resolve_metric("operating_income"),
                current["operating_income"],
                context=context,
                period=periods.period,
                comparison=prior("operating_income"),
                comparison_period=comparison_period,
                inputs={
                    "gross_profit": current["gross_profit"],
                    "operating_expenses": current["operating_expenses"],
                },
            ),
        ]
        previous_margin = None
        if comparison:
            previous_margin = safe_percentage(
                comparison["operating_income"], comparison["revenue"]
            )
        if gross_margin is not None:
            metrics.append(
                financial_metric(
                    resolve_metric("gross_margin_pct"),
                    gross_margin,
                    context=context,
                    period=periods.period,
                    comparison=(
                        safe_percentage(comparison["gross_profit"], comparison["revenue"])
                        if comparison
                        else None
                    ),
                    comparison_period=comparison_period,
                    inputs={
                        "gross_profit": current["gross_profit"],
                        "revenue": current["revenue"],
                    },
                )
            )
        if operating_margin is not None:
            metrics.append(
                financial_metric(
                    resolve_metric("operating_margin_pct"),
                    operating_margin,
                    context=context,
                    period=periods.period,
                    comparison=previous_margin,
                    comparison_period=comparison_period,
                    inputs={
                        "operating_income": current["operating_income"],
                        "revenue": current["revenue"],
                    },
                )
            )

        breakdown: list = []
        for key, label, _sign in WALK:
            previous_value = comparison[key] if comparison else None
            breakdown.append(
                make_dimension_value(
                    Dimension.QUARTER,
                    key,
                    current[key],
                    label=label,
                    metric=key,
                    comparison_value=previous_value,
                )
            )

        if comparison and operating_margin is not None and previous_margin is not None:
            breakdown.append(
                make_dimension_value(
                    Dimension.QUARTER,
                    "operating_margin_pct",
                    operating_margin,
                    label="Operating margin",
                    metric="operating_margin_pct",
                    comparison_value=previous_margin,
                )
            )

        if comparison:
            opex_as_revenue = safe_percentage(current["operating_expenses"], current["revenue"])
            previous_opex_ratio = safe_percentage(
                comparison["operating_expenses"], comparison["revenue"]
            )
            if opex_as_revenue is not None and previous_opex_ratio is not None:
                context.warn(
                    "Operating expense intensity is the key driver of margin movement: "
                    f"{previous_opex_ratio:.2f}% of revenue in {periods.comparison_period} "
                    f"versus {opex_as_revenue:.2f}% in {periods.period}."
                )

        return AnalyzerOutput(
            metrics=metrics,
            breakdown=breakdown,
            methodology=[
                "gross_profit = revenue - cogs",
                "operating_income = gross_profit - operating_expenses",
                "gross_margin_pct = gross_profit / revenue * 100",
                "operating_margin_pct = operating_income / revenue * 100",
            ],
            period=periods.period,
            comparison_period=periods.comparison_period,
            row_count=len(breakdown),
        )
