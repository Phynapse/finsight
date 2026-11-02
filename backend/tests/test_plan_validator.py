"""The plan validator is the security boundary: nothing runs without passing it."""

from __future__ import annotations

import pytest

from app.analytics.validator import PlanValidator
from app.core.errors import PlanValidationError, UnknownAnalysisTypeError, UnknownMetricError
from app.data.repository import DatasetRepository
from app.models.enums import AnalysisType, Dimension
from app.schemas.analysis import AnalysisFilter, AnalysisPlan


@pytest.fixture(scope="module")
def validator(repository: DatasetRepository) -> PlanValidator:
    return PlanValidator(repository)


def plan(**overrides) -> AnalysisPlan:
    payload = {
        "analysis_type": AnalysisType.METRIC_SNAPSHOT,
        "metric": "revenue",
        "period": "2024-Q4",
    }
    payload.update(overrides)
    return AnalysisPlan(**payload)


class TestAcceptedPlans:
    def test_a_minimal_plan_is_valid(self, validator):
        validator.validate(plan())

    def test_an_allow_listed_dimension_is_valid(self, validator):
        validator.validate(
            plan(
                analysis_type=AnalysisType.EXPENSE_ANALYSIS,
                metric="total_expense",
                dimensions=[Dimension.DEPARTMENT],
            )
        )

    def test_an_allow_listed_filter_is_valid(self, validator):
        validator.validate(
            plan(
                analysis_type=AnalysisType.EXPENSE_ANALYSIS,
                metric="total_expense",
                filters=[AnalysisFilter(field="department", values=["Engineering"])],
            )
        )


class TestRejectedPlans:
    def test_unknown_metric(self, validator):
        with pytest.raises(UnknownMetricError):
            validator.validate(plan(metric="profit"))

    def test_metric_outside_the_analysis_scope(self, validator):
        with pytest.raises(PlanValidationError) as error:
            validator.validate(
                plan(analysis_type=AnalysisType.VENDOR_SPEND, metric="operating_margin_pct")
            )
        fields = [problem["field"] for problem in error.value.details["problems"]]
        assert "metric" in fields

    def test_unknown_period(self, validator):
        with pytest.raises(PlanValidationError) as error:
            validator.validate(plan(period="2099-Q1"))
        messages = str(error.value.details["problems"])
        assert "2099-Q1" in messages

    def test_period_cannot_compare_with_itself(self, validator):
        with pytest.raises(PlanValidationError):
            validator.validate(plan(comparison_period="2024-Q4"))

    def test_period_end_before_period(self, validator):
        with pytest.raises(PlanValidationError):
            validator.validate(plan(period_end="2023-Q1"))

    def test_disallowed_dimension(self, validator):
        """Profitability only walks the statement, so no ledger dimension."""
        with pytest.raises(PlanValidationError):
            validator.validate(
                plan(
                    analysis_type=AnalysisType.PROFITABILITY,
                    metric="operating_income",
                    dimensions=[Dimension.VENDOR],
                )
            )

    def test_disallowed_filter_field(self, validator):
        with pytest.raises(PlanValidationError):
            validator.validate(
                plan(
                    analysis_type=AnalysisType.EXPENSE_ANALYSIS,
                    metric="total_expense",
                    filters=[AnalysisFilter(field="vendor_id", values=["V-001"])],
                )
            )

    def test_duplicate_dimensions_are_rejected_by_the_schema(self):
        with pytest.raises(ValueError):
            plan(
                analysis_type=AnalysisType.EXPENSE_ANALYSIS,
                metric="total_expense",
                dimensions=[Dimension.CATEGORY, Dimension.CATEGORY],
            )

    def test_limit_above_the_maximum_is_rejected_by_the_schema(self):
        with pytest.raises(ValueError):
            plan(limit=5_000)

    def test_problems_are_reported_together_not_one_at_a_time(self, validator):
        with pytest.raises(PlanValidationError) as error:
            validator.validate(
                plan(
                    analysis_type=AnalysisType.PROFITABILITY,
                    metric="operating_income",
                    period="2099-Q1",
                    dimensions=[Dimension.VENDOR],
                    filters=[AnalysisFilter(field="vendor_id", values=["V-001"])],
                )
            )
        fields = {problem["field"] for problem in error.value.details["problems"]}
        assert {"period", "dimensions", "filters"} <= fields


class TestSchemaLimits:
    def test_question_length_is_bounded(self):
        with pytest.raises(ValueError):
            AnalysisFilter(field="department", values=["x" * 500])

    def test_too_many_filters_are_rejected(self):
        filters = [AnalysisFilter(field="department", values=["a"])] * 6
        with pytest.raises(ValueError):
            plan(
                analysis_type=AnalysisType.EXPENSE_ANALYSIS,
                metric="total_expense",
                filters=filters,
            )

    def test_malformed_period_is_rejected(self):
        with pytest.raises(ValueError):
            plan(period="Q4-2024")

    def test_unknown_field_is_rejected(self):
        """A typo must fail loudly rather than be silently ignored."""
        with pytest.raises(ValueError):
            AnalysisPlan(
                analysis_type=AnalysisType.METRIC_SNAPSHOT,
                metric="revenue",
                sql="select * from transactions",
            )