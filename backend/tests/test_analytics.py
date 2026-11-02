"""Analyser correctness.

Each test recomputes the expected figure independently, in plain Python, from
the source dataset. If an analyser and this test agree, the number is not an
artefact of the implementation.
"""

from __future__ import annotations

import pytest

from app.analytics.base import resolve_month_scope
from app.analytics.factory import build_registry
from app.data.integrity import net_cash_spend
from app.analytics.validator import PlanValidator
from app.core.errors import InvalidPeriodError
from app.data.repository import DatasetRepository
from app.models.catalog import resolve_analysis_type
from app.models.enums import AnalysisType, Dimension
from app.schemas.analysis import AnalysisPlan

LATEST = "2024-Q4"
PRIOR = "2024-Q3"


def run_plan(repository: DatasetRepository, plan: AnalysisPlan):
    """Validate and execute a plan exactly as the API would."""
    PlanValidator(repository).validate(plan)
    spec = resolve_analysis_type(plan.analysis_type)
    context = build_context(repository, plan, spec)
    return build_registry().get(plan.analysis_type).run(context), context


def build_context(repository: DatasetRepository, plan: AnalysisPlan, spec):
    from app.analytics.base import AnalysisContext

    return AnalysisContext(repository=repository, plan=plan, spec=spec)


def metric_by_id(result, metric_id: str):
    matches = [metric for metric in result.metrics if metric.id == metric_id]
    assert matches, f"{metric_id} missing from {[m.id for m in result.metrics]}"
    return matches[0]


@pytest.fixture(scope="module")
def statement(repository: DatasetRepository):
    return repository.frame("financial_data").set_index("period", drop=False)


class TestRegistry:
    def test_every_catalogued_analysis_type_is_implemented(self):
        registry = build_registry()
        registry.validate_catalog_coverage()
        assert len(registry.registered()) == len(AnalysisType)

    def test_unknown_analysis_type_raises(self):
        with pytest.raises(Exception):
            build_registry().get("not_a_type")


class TestRevenuePerformance:
    def test_gross_profit_is_recomputed_not_read(self, repository, statement):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.REVENUE_PERFORMANCE,
            metric="revenue",
            period=LATEST,
            comparison_period=PRIOR,
        )
        result, _ = run_plan(repository, plan)
        row = statement.loc[LATEST]
        gross_profit = metric_by_id(result, "gross_profit")
        assert gross_profit.value == pytest.approx(
            float(row["revenue"]) - float(row["cogs"]), abs=0.01
        )
        assert gross_profit.formula_inputs["revenue"] == pytest.approx(float(row["revenue"]))

    def test_gross_margin_is_a_percentage(self, repository, statement):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.REVENUE_PERFORMANCE,
            metric="gross_margin_pct",
            period=LATEST,
            comparison_period=PRIOR,
        )
        result, _ = run_plan(repository, plan)
        margin = metric_by_id(result, "gross_margin_pct")
        row = statement.loc[LATEST]
        expected = (float(row["revenue"]) - float(row["cogs"])) / float(row["revenue"]) * 100
        assert margin.value == pytest.approx(expected, abs=0.01)
        assert margin.unit.value == "percent"

    def test_metric_carries_its_own_comparison(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.REVENUE_PERFORMANCE,
            metric="revenue",
            period=LATEST,
            comparison_period=PRIOR,
        )
        result, _ = run_plan(repository, plan)
        revenue = metric_by_id(result, "revenue")
        assert revenue.comparison_period == PRIOR
        assert revenue.comparison_value is not None
        assert revenue.change == pytest.approx(revenue.value - revenue.comparison_value, abs=0.01)
        assert revenue.percentage_change == pytest.approx(
            (revenue.value - revenue.comparison_value) / revenue.comparison_value * 100, abs=0.01
        )

    def test_unknown_period_is_rejected(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.REVENUE_PERFORMANCE,
            metric="revenue",
            period="1999-Q1",
        )
        with pytest.raises(Exception):
            run_plan(repository, plan)


class TestProfitability:
    def test_operating_income_and_margin(self, repository, statement):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.PROFITABILITY,
            metric="operating_income",
            period=LATEST,
            comparison_period=PRIOR,
        )
        result, _ = run_plan(repository, plan)
        row = statement.loc[LATEST]
        operating = metric_by_id(result, "operating_income")
        margin = metric_by_id(result, "operating_margin_pct")

        expected_income = float(row["revenue"]) - float(row["cogs"]) - float(row["operating_expenses"])
        assert operating.value == pytest.approx(expected_income, abs=0.01)
        assert margin.value == pytest.approx(
            expected_income / float(row["revenue"]) * 100, abs=0.01
        )

    def test_breakdown_walks_the_statement_in_order(self, repository, statement):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.PROFITABILITY,
            metric="operating_income",
            period=LATEST,
            comparison_period=PRIOR,
        )
        result, _ = run_plan(repository, plan)
        keys = [row.key for row in result.breakdown]
        assert keys[:5] == [
            "revenue",
            "cogs",
            "gross_profit",
            "operating_expenses",
            "operating_income",
        ]

    def test_breakdown_rows_name_their_own_metric(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.PROFITABILITY,
            metric="operating_margin_pct",
            period=LATEST,
            comparison_period=PRIOR,
        )
        result, _ = run_plan(repository, plan)
        revenue_row = next(row for row in result.breakdown if row.key == "revenue")
        assert revenue_row.metric == "revenue"

    def test_early_period_has_no_prior_quarter(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.PROFITABILITY,
            metric="operating_income",
            period="2023-Q1",
            comparison_mode="prior_quarter",
        )
        with pytest.raises(InvalidPeriodError):
            run_plan(repository, plan)


class TestExpenseVariance:
    def test_net_ledger_movement_equals_the_statement_movement(
        self, repository, statement
    ):
        """The ledger must explain the statement, not contradict it."""
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_VARIANCE,
            metric="operating_expenses",
            period=LATEST,
            comparison_period=PRIOR,
            limit=25,
        )
        result, _ = run_plan(repository, plan)
        statement_change = float(statement.loc[LATEST, "operating_expenses"]) - float(
            statement.loc[PRIOR, "operating_expenses"]
        )
        ledger_change = sum(row.change or 0.0 for row in result.breakdown)
        assert ledger_change == pytest.approx(statement_change, abs=0.05)

    def test_contributions_sum_to_the_total_change(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_VARIANCE,
            metric="operating_expenses",
            period=LATEST,
            comparison_period=PRIOR,
            limit=25,
        )
        result, _ = run_plan(repository, plan)
        rows = [row for row in result.breakdown if row.contribution_to_change_pct is not None]
        assert rows
        assert sum(row.contribution_to_change_pct for row in rows) == pytest.approx(100.0, abs=0.05)

    def test_a_truncated_breakdown_says_so(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_VARIANCE,
            metric="operating_expenses",
            period=LATEST,
            comparison_period=PRIOR,
            limit=3,
        )
        result, context = run_plan(repository, plan)
        assert len(result.breakdown) == 3
        assert result.row_count > 3
        assert any("omitted" in warning for warning in context.warnings)

    def test_net_spend_is_expense_minus_credit(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_ANALYSIS,
            metric="total_expense",
            period=LATEST,
            dimensions=[Dimension.CATEGORY],
            limit=25,
        )
        result, _ = run_plan(repository, plan)

        transactions = repository.frame("transactions")
        scope = transactions[transactions["period"].isin(["2024-10", "2024-11", "2024-12"])]
        expenses = float(scope[scope["transaction_type"] == "expense"]["amount"].sum())
        credits = float(scope[scope["transaction_type"] == "credit"]["amount"].sum())
        assert sum(row.value for row in result.breakdown) == pytest.approx(
            expenses - credits, abs=0.05
        )

    def test_a_period_cannot_be_compared_with_itself(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_VARIANCE,
            metric="operating_expenses",
            period=LATEST,
            comparison_period=LATEST,
        )
        with pytest.raises(Exception):
            run_plan(repository, plan)


class TestTrend:
    def test_series_is_ordered_and_compares_consecutively(self, repository):
        plan = AnalysisPlan(analysis_type=AnalysisType.TREND, metric="revenue")
        result, _ = run_plan(repository, plan)
        periods = [row.key for row in result.series]
        assert periods == sorted(periods)
        assert len(periods) == 8
        for previous, current in zip(result.series, result.series[1:], strict=False):
            assert current.comparison_value == previous.value
            assert current.change == pytest.approx(current.value - previous.value, abs=0.01)

    def test_headline_metric_compares_the_first_and_last_point(self, repository):
        plan = AnalysisPlan(analysis_type=AnalysisType.TREND, metric="revenue")
        result, _ = run_plan(repository, plan)
        metric = result.metrics[0]
        assert metric.value == result.series[-1].value
        assert metric.comparison_value == result.series[0].value
        assert metric.comparison_period == result.series[0].key

    def test_no_self_comparison_at_the_first_point(self, repository):
        plan = AnalysisPlan(analysis_type=AnalysisType.TREND, metric="revenue")
        result, _ = run_plan(repository, plan)
        assert result.series[0].comparison_value is None
        assert result.series[0].change is None


class TestBudgetVariance:
    def test_variance_is_actual_minus_budget(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.BUDGET_VARIANCE,
            metric="budget_variance",
            period=LATEST,
        )
        result, _ = run_plan(repository, plan)
        variance = metric_by_id(result, "budget_variance")
        budget = metric_by_id(result, "budget_amount")

        budgets = repository.frame("budgets")
        scope = budgets[budgets["period"].isin(["2024-10", "2024-11", "2024-12"])]
        assert budget.value == pytest.approx(float(scope["budget_amount"].sum()), abs=0.01)
        assert variance.value == pytest.approx(
            float(scope["actual_amount"].sum()) - float(scope["budget_amount"].sum()), abs=0.01
        )

    def test_utilisation_is_a_percentage(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.BUDGET_VARIANCE,
            metric="budget_utilisation_pct",
            period=LATEST,
        )
        result, _ = run_plan(repository, plan)
        utilisation = metric_by_id(result, "budget_utilisation_pct")
        budget = metric_by_id(result, "budget_amount")
        variance = metric_by_id(result, "budget_variance")
        actual = budget.value + variance.value
        assert utilisation.value == pytest.approx(actual / budget.value * 100, abs=0.01)
        assert utilisation.formula_inputs["actual_amount"] == pytest.approx(actual, abs=0.01)

    def test_a_truncated_breakdown_says_so(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.BUDGET_VARIANCE,
            metric="budget_variance",
            period=LATEST,
            dimensions=[Dimension.CATEGORY],
            limit=3,
        )
        result, context = run_plan(repository, plan)
        assert len(result.breakdown) == 3
        assert result.row_count > 3
        assert any("omitted" in warning for warning in context.warnings)


class TestVendorSpend:
    def test_vendor_rows_reconcile_to_the_ledger(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.VENDOR_SPEND, metric="total_expense", limit=25
        )
        result, _ = run_plan(repository, plan)
        top = metric_by_id(result, "top_vendor_spend")

        cash = repository.frame("transactions")
        cash = cash[cash["vendor_id"].notna()].copy()
        cash["net"] = net_cash_spend(cash)
        ledger = cash.groupby("vendor_id")["net"].sum()
        assert top.value == pytest.approx(float(ledger.max()), abs=0.01)
        assert len(result.breakdown) == int(ledger.shape[0])

    def test_concentration_is_the_top_five_share_of_net_spend(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.VENDOR_SPEND, metric="total_expense", limit=25
        )
        result, _ = run_plan(repository, plan)
        concentration = metric_by_id(result, "vendor_concentration_pct")

        cash = repository.frame("transactions")
        cash = cash[cash["vendor_id"].notna()].copy()
        cash["net"] = net_cash_spend(cash)
        per_vendor = cash.groupby("vendor_id")["net"].sum().sort_values(ascending=False)
        expected = float(per_vendor.head(5).sum()) / float(per_vendor.sum()) * 100
        assert concentration.value == pytest.approx(expected, abs=0.05)


class TestMetricSnapshot:
    def test_snapshot_returns_one_metric_with_provenance(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.METRIC_SNAPSHOT, metric="revenue", period=LATEST
        )
        result, _ = run_plan(repository, plan)
        assert len(result.metrics) == 1
        metric = result.metrics[0]
        assert metric.source_dataset == "financial_data"
        assert metric.calculation


class TestMonthScope:
    def test_quarter_maps_to_three_months(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_ANALYSIS,
            metric="total_expense",
            period=LATEST,
        )
        assert resolve_month_scope(plan, repository) == ["2024-10", "2024-11", "2024-12"]

    def test_no_period_means_every_month(self, repository):
        plan = AnalysisPlan(analysis_type=AnalysisType.EXPENSE_ANALYSIS, metric="total_expense")
        assert len(resolve_month_scope(plan, repository)) == 12

    def test_period_end_extends_the_range(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_ANALYSIS,
            metric="total_expense",
            period="2024-Q3",
            period_end=LATEST,
        )
        assert resolve_month_scope(plan, repository) == [
            "2024-07",
            "2024-08",
            "2024-09",
            "2024-10",
            "2024-11",
            "2024-12",
        ]

    def test_a_period_outside_the_ledger_is_rejected(self, repository):
        plan = AnalysisPlan(
            analysis_type=AnalysisType.EXPENSE_ANALYSIS,
            metric="total_expense",
            period="2023-Q1",
        )
        with pytest.raises(InvalidPeriodError):
            resolve_month_scope(plan, repository)
