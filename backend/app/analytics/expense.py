"""Expense analysis: cash versus non-cash, with ledger attribution."""

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
    month_range,
    resolve_comparison,
    safe_average,
    safe_percentage,
)
from app.models.catalog import resolve_metric
from app.models.enums import AnalysisType, Dimension


class ExpenseAnalyzer(Analyzer):
    """Operating expense split into cash and non-cash, then attributed.

    The income statement gives the authoritative total; the ledger is used to
    explain where that total moved. Because the ledger reconciles to the
    statement exactly, the two can never disagree silently.
    """

    analysis_type = AnalysisType.EXPENSE_ANALYSIS

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        periods = resolve_comparison(plan, context.repository)
        if periods.period is None:
            from app.core.errors import InvalidPeriodError

            raise InvalidPeriodError("A period is required for expense analysis.")

        statement = context.statement_frame().set_index("period", drop=False)
        row = statement[statement["period"] == periods.period].iloc[0]
        cash_opex = float(row["cash_operating_expenses"])
        non_cash = float(row["non_cash_operating_expenses"])
        total_opex = round(cash_opex + non_cash, 2)

        metrics = [
            financial_metric(
                resolve_metric("operating_expenses"),
                total_opex,
                context=context,
                period=periods.period,
                inputs={
                    "cash_operating_expenses": cash_opex,
                    "non_cash_operating_expenses": non_cash,
                },
            ),
            financial_metric(
                resolve_metric("cash_operating_expenses"),
                cash_opex,
                context=context,
                period=periods.period,
            ),
            financial_metric(
                resolve_metric("non_cash_operating_expenses"),
                non_cash,
                context=context,
                period=periods.period,
            ),
        ]

        cash_share = safe_percentage(cash_opex, total_opex)
        if cash_share is not None:
            context.warn(
                f"Cash spend is {cash_share:.2f}% of operating expense; the remaining "
                f"{round(100 - cash_share, 2):.2f}% is non-cash."
            )

        breakdown: list = []
        methodology = [
            "operating_expenses = cash_operating_expenses + non_cash_operating_expenses",
            "ledger net spend = sum(expense amounts) - sum(credit amounts)",
            "ledger groups are taken from transactions.csv for the same quarter",
        ]

        if plan.dimensions:
            dimension = plan.dimensions[0]
            column = LEDGER_DIMENSION_COLUMN[dimension]
            breakdown, extra = self._dimension_breakdown(
                context, dimension, column, periods.period, periods.comparison_period
            )
            methodology.extend(extra)
        else:
            breakdown, methodology_extra = self._default_breakdown(
                context, periods.period, periods.comparison_period
            )
            methodology.extend(methodology_extra)

        row_count = len(breakdown)
        return AnalyzerOutput(
            metrics=metrics,
            breakdown=breakdown,
            methodology=methodology,
            period=periods.period,
            comparison_period=periods.comparison_period,
            row_count=row_count,
        )

    # -- breakdown strategies ---------------------------------------------
    def _default_breakdown(
        self, context: AnalysisContext, period: str | None, comparison_period: str | None
    ) -> tuple[list, list[str]]:
        """Cash versus non-cash, which is the primary expense split."""
        statement = context.statement_frame().set_index("period", drop=False)
        current = statement[statement["period"] == period].iloc[0]
        comparison = (
            statement[statement["period"] == comparison_period].iloc[0]
            if comparison_period
            else None
        )
        total = float(current["operating_expenses"])
        transactions = context.transactions_frame()
        scoped = transactions[transactions["period"].isin(month_range(str(period)))]
        counts = {
            "Cash operating expenses": int((scoped["is_non_cash"] == False).sum()),  # noqa: E712
            "Non-cash operating expenses": int((scoped["is_non_cash"] == True).sum()),  # noqa: E712
        }
        rows = []
        for label, column in (
            ("Cash operating expenses", "cash_operating_expenses"),
            ("Non-cash operating expenses", "non_cash_operating_expenses"),
        ):
            previous = float(comparison[column]) if comparison is not None else None
            rows.append(
                make_dimension_value(
                    Dimension.CATEGORY,
                    column,
                    float(current[column]),
                    label=label,
                    comparison_value=previous,
                    total=total,
                    transaction_count=counts[label],
                )
            )
        return rows, ["default breakdown is the cash / non-cash split"]

    def _dimension_breakdown(
        self,
        context: AnalysisContext,
        dimension: Dimension,
        column: str,
        period: str | None,
        comparison_period: str | None,
    ) -> tuple[list, list[str]]:
        if period is None:  # pragma: no cover - guarded upstream
            return [], []
        transactions = apply_filters(
            context.transactions_frame(), context.plan, context, context.spec.allowed_filters
        )
        current = group_spend(
            ledger_for_period(transactions, month_range(period)),
            column,
            limit=context.plan.limit,
        )
        comparison: pd.DataFrame | None = None
        if comparison_period:
            comparison = group_spend(
                ledger_for_period(transactions, month_range(comparison_period)), column
            )

        total = float(current["net_amount"].sum())
        rows: list = []
        for record in current.itertuples(index=False):
            key = str(getattr(record, column))
            previous = None
            if comparison is not None:
                match = comparison[comparison[column] == key]
                if not match.empty:
                    previous = float(match.iloc[0]["net_amount"])
            rows.append(
                make_dimension_value(
                    dimension,
                    key,
                    float(record.net_amount),
                    label=key,
                    comparison_value=previous,
                    total=total,
                    transaction_count=int(record.line_count),
                )
            )
        return rows, [
            f"grouped by {dimension.value} ({column})",
            "net spend per group, largest absolute movement first",
        ]


class ExpenseVarianceAnalyzer(Analyzer):
    """Period-over-period movement in operating expense, attributed to the ledger.

    This is the analyser behind the headline question: *why* did operating
    expense change? The answer is a contribution table computed in Pandas, not
    a narrative guessed by a language model.
    """

    analysis_type = AnalysisType.EXPENSE_VARIANCE

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        periods = resolve_comparison(plan, context.repository)
        if periods.period is None or periods.comparison_period is None:
            from app.core.errors import InvalidPeriodError

            raise InvalidPeriodError(
                "Expense variance requires both a period and a comparison period.",
                details={"period": periods.period, "comparison_period": periods.comparison_period},
            )

        statement = context.statement_frame().set_index("period", drop=False)
        current_row = statement[statement["period"] == periods.period].iloc[0]
        comparison_row = statement[statement["period"] == periods.comparison_period].iloc[0]

        metrics = [
            financial_metric(
                resolve_metric("operating_expenses"),
                float(current_row["operating_expenses"]),
                context=context,
                period=periods.period,
                comparison=float(comparison_row["operating_expenses"]),
                comparison_period=periods.comparison_period,
                inputs={
                    "cash_operating_expenses": float(current_row["cash_operating_expenses"]),
                    "non_cash_operating_expenses": float(
                        current_row["non_cash_operating_expenses"]
                    ),
                },
            ),
            financial_metric(
                resolve_metric("cash_operating_expenses"),
                float(current_row["cash_operating_expenses"]),
                context=context,
                period=periods.period,
                comparison=float(comparison_row["cash_operating_expenses"]),
                comparison_period=periods.comparison_period,
            ),
            financial_metric(
                resolve_metric("non_cash_operating_expenses"),
                float(current_row["non_cash_operating_expenses"]),
                context=context,
                period=periods.period,
                comparison=float(comparison_row["non_cash_operating_expenses"]),
                comparison_period=periods.comparison_period,
            ),
        ]

        total_change = round(
            float(current_row["operating_expenses"]) - float(comparison_row["operating_expenses"]), 2
        )

        dimension = plan.dimensions[0] if plan.dimensions else Dimension.CATEGORY
        column = LEDGER_DIMENSION_COLUMN[dimension]

        transactions = apply_filters(
            context.transactions_frame(), plan, context, context.spec.allowed_filters
        )
        current = group_spend(
            ledger_for_period(transactions, month_range(periods.period)), column
        )
        comparison = group_spend(
            ledger_for_period(transactions, month_range(periods.comparison_period)), column
        )

        keys = sorted(set(current[column].tolist()) | set(comparison[column].tolist()))
        movements: list = []
        for key in keys:
            current_value = self._value(current, column, key)
            previous_value = self._value(comparison, column, key)
            movements.append(
                make_dimension_value(
                    dimension,
                    str(key),
                    current_value,
                    label=str(key),
                    comparison_value=previous_value,
                    transaction_count=self._count(current, column, key),
                    total_change=total_change,
                )
            )
        movements.sort(key=lambda row: (abs(row.change or 0.0), row.key), reverse=True)
        if len(movements) > plan.limit:
            context.warn(
                f"{len(movements)} groups moved but only the {plan.limit} largest are "
                "shown; the remaining groups are omitted."
            )

        methodology = [
            "change = period value - comparison period value",
            "percentage_change = change / abs(comparison value) * 100",
            "contribution_to_change_pct = change / total change * 100",
            f"groups ranked by absolute contribution to the {total_change:,.2f} movement",
        ]
        if total_change == 0.0:
            context.warn("Total operating expense is unchanged; contributions are all zero.")

        return AnalyzerOutput(
            metrics=metrics,
            breakdown=movements[: plan.limit],
            methodology=methodology,
            period=periods.period,
            comparison_period=periods.comparison_period,
            row_count=len(movements),
        )

    @staticmethod
    def _value(grouped: pd.DataFrame, column: str, key: str) -> float:
        matches = grouped[grouped[column] == key]
        if matches.empty:
            return 0.0
        return round(float(matches.iloc[0]["net_amount"]), 2)

    @staticmethod
    def _count(grouped: pd.DataFrame, column: str, key: str) -> int:
        matches = grouped[grouped[column] == key]
        if matches.empty:
            return 0
        return int(matches.iloc[0]["line_count"])
