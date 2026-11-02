"""Budget variance analysis."""

from __future__ import annotations

import pandas as pd

from app.analytics.base import (
    financial_metric,
    BUDGET_DIMENSION_COLUMN,
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    apply_filters,
    make_dimension_value,
    resolve_month_scope,
    safe_average,
    safe_percentage,
)
from app.core.errors import NoDataForPlanError
from app.models.catalog import resolve_metric
from app.models.enums import AnalysisType, Dimension


class BudgetVarianceAnalyzer(Analyzer):
    """Actual spend against approved budget.

    Variance is recomputed from ``budget_amount`` and ``actual_amount`` rather
    than read from the file's convenience column, so the reported variance is
    always traceable to the two source figures. Positive variance is overspend.
    """

    analysis_type = AnalysisType.BUDGET_VARIANCE

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        budgets = apply_filters(context.budgets_frame(), plan, context, context.spec.allowed_filters)
        months = resolve_month_scope(plan, context.repository)
        scoped = budgets[budgets["period"].isin(months)]

        if scoped.empty:
            raise NoDataForPlanError(
                "No budget lines match this plan.",
                details={"months": months, "filters": [item.field for item in plan.filters]},
            )

        dimension = plan.dimensions[0] if plan.dimensions else Dimension.CATEGORY
        column = BUDGET_DIMENSION_COLUMN.get(dimension, "category")

        grouped = self._aggregate(scoped, column)
        total_budget = round(float(scoped["budget_amount"].sum()), 2)
        total_actual = round(float(scoped["actual_amount"].sum()), 2)
        total_variance = round(total_actual - total_budget, 2)
        utilisation = safe_percentage(total_actual, total_budget)

        metrics = [
            financial_metric(
                resolve_metric("budget_amount"), total_budget, context=context, period=plan.period
            ),
            financial_metric(
                resolve_metric("budget_variance"),
                total_variance,
                context=context,
                period=plan.period,
                inputs={"budget_amount": total_budget, "actual_amount": total_actual},
            ),
        ]
        if utilisation is not None:
            metrics.append(
                financial_metric(
                    resolve_metric("budget_utilisation_pct"),
                    utilisation,
                    context=context,
                    period=plan.period,
                    inputs={"budget_amount": total_budget, "actual_amount": total_actual},
                )
            )

        rows = [
            make_dimension_value(
                dimension,
                str(record[column]),
                float(record["variance"]),
                label=str(record[column]),
                total=total_variance if total_variance else None,
                transaction_count=int(record["line_count"]),
            )
            for record in grouped.to_dict(orient="records")
        ]
        rows.sort(key=lambda row: (abs(row.value), row.key), reverse=True)
        if len(rows) > plan.limit:
            context.warn(
                f"{len(rows)} budget groups were compared but only the {plan.limit} largest "
                "are shown; the remainder are omitted."
            )

        overspent = [row for row in rows if row.value > 0]
        if overspent:
            worst = overspent[0]
            share = worst.contribution_to_change_pct
            context.warn(
                f"Largest overspend: {worst.label} at {worst.value:,.2f}"
                + (f" ({share:.2f}% of the net variance)." if share is not None else ".")
            )
        underdrawn = [row for row in rows if row.value < 0]
        if underdrawn:
            context.warn(
                f"{len(underdrawn)} budget lines were not fully drawn, so the net variance "
                "hides offsetting movements."
            )

        return AnalyzerOutput(
            metrics=metrics,
            breakdown=rows[: plan.limit],
            methodology=[
                "variance = actual_amount - budget_amount (positive is overspend)",
                "utilisation_pct = actual_amount / budget_amount * 100",
                "variance is recomputed from source columns, not read from the file",
                f"scope: {len(scoped)} budget lines across {len(months)} month(s)",
            ],
            period=plan.period,
            comparison_period=plan.comparison_period,
            row_count=len(rows),
        )

    @staticmethod
    def _aggregate(budgets: pd.DataFrame, column: str) -> pd.DataFrame:
        return (
            budgets.groupby(column, as_index=False)
            .agg(
                budget=("budget_amount", "sum"),
                actual=("actual_amount", "sum"),
                line_count=("budget_amount", "size"),
            )
            .assign(variance=lambda frame: (frame["actual"] - frame["budget"]).round(2))
            .sort_values(by=["variance", column], ascending=[False, True], kind="stable")
            .reset_index(drop=True)
        )
