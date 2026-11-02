"""The AI layer: interpretation, explanation and the grounding guarantee.

The rule-based implementations are the Phase 1 default and the reference
contract for the Phase 2 language model, so their behaviour is pinned here.
"""

from __future__ import annotations

import pytest

from app.analytics.validator import PlanValidator
from app.ai.base import AnalysisPlanner, ExplanationGenerator, QuestionInterpreter
from app.ai.factory import build_pipeline, require_llm
from app.ai.rules import (
    DeterministicAnalysisPlanner,
    DeterministicQuestionInterpreter,
    RuleBasedExplanationGenerator,
    detect_period,
)
from app.core.config import Settings
from app.core.errors import QuestionRejectedError
from app.data.repository import DatasetRepository
from app.models.enums import AnalysisType, ComparisonMode


@pytest.fixture(scope="module")
def interpreter(repository: DatasetRepository) -> DeterministicQuestionInterpreter:
    return DeterministicQuestionInterpreter(repository)


@pytest.fixture(scope="module")
def planner(repository: DatasetRepository) -> DeterministicAnalysisPlanner:
    return DeterministicAnalysisPlanner(repository)


class TestInterpreter:
    def test_maps_a_metric_question_to_an_analysis(self, interpreter):
        result = interpreter.interpret("How did operating margin change in 2024-Q4?")
        assert result.metric == "operating_margin_pct"
        assert result.analysis_type is not None
        assert result.period == "2024-Q4"
        assert result.confidence > 0

    def test_rejects_an_unsupported_question(self, interpreter):
        result = interpreter.interpret("What is the weather tomorrow?")
        assert result.metric is None
        assert result.analysis_type is None
        assert result.confidence == 0.0

    def test_restatement_quotes_the_question(self, interpreter):
        result = interpreter.interpret("Why did revenue fall in 2024-Q4?")
        assert result.restated_question.startswith("'Why did revenue fall in 2024-Q4'.")
        assert "Revenue" in result.restated_question

    def test_budget_wording_routes_to_budget_variance(self, interpreter):
        """'against budget' must beat the generic 'expense' keyword."""
        result = interpreter.interpret(
            "How much did operating expenses vary against budget in 2024-Q4?"
        )
        assert result.analysis_type is AnalysisType.BUDGET_VARIANCE
        assert result.metric == "budget_variance"

    def test_a_substituted_metric_is_disclosed(self, interpreter):
        result = interpreter.interpret(
            "How much did operating expenses vary against budget in 2024-Q4?"
        )
        assert any("not measured by" in note for note in result.notes)

    def test_a_guessed_period_is_disclosed(self, interpreter):
        result = interpreter.interpret("Why are operating expenses so high?")
        assert any("defaulted to the latest period" in note for note in result.notes)

    def test_vendor_wording_selects_the_vendor_dimension(self, interpreter):
        result = interpreter.interpret("Which vendors drive the most spend?")
        assert result.analysis_type is AnalysisType.VENDOR_SPEND
        assert "vendor" in result.dimensions

    def test_trend_wording_uses_no_period(self, interpreter):
        result = interpreter.interpret("What is the revenue trend?")
        assert result.analysis_type is AnalysisType.TREND
        assert result.period is None

    def test_a_quarter_with_no_year_uses_the_latest_matching_year(self, interpreter):
        result = interpreter.interpret("What was revenue in Q4?")
        assert result.period == "2024-Q4"

    def test_an_impossible_period_is_disclosed_not_silently_remapped(
        self, interpreter, repository
    ):
        """1998 is outside the data; the answer must say which period it used."""
        result = interpreter.interpret("What was revenue in 1998-Q2?")
        assert result.period == repository.latest_period
        assert any("defaulted to the latest period" in note for note in result.notes)


class TestPeriodDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("revenue in 2023-Q2", "2023-Q2"),
            ("revenue in 2023 Q2", "2023-Q2"),
            ("revenue for Q3 2024", "2024-Q3"),
        ],
    )
    def test_explicit_quarters(self, repository, text, expected):
        period, _comparison, _mode = detect_period(text, repository.periods)
        assert period == expected

    def test_last_quarter_resolves_to_the_penultimate_period(self, repository):
        period, _comparison, mode = detect_period("revenue last quarter", repository.periods)
        assert period == "2024-Q3"
        assert mode == "prior_quarter"

    def test_year_over_year_resolves_to_the_same_quarter_last_year(self, repository):
        period, comparison, _mode = detect_period(
            "revenue year over year in 2024-Q4", repository.periods
        )
        assert (period, comparison) == ("2024-Q4", "2023-Q4")

    def test_no_period_wording_yields_nothing(self, repository):
        period, comparison, mode = detect_period("what is revenue", repository.periods)
        assert (period, comparison, mode) == (None, None, "none")


class TestPlanner:
    def test_builds_a_validatable_plan(self, repository, interpreter, planner):
        interpretation = interpreter.interpret("Why did operating margin change in 2024-Q4?")
        plans = planner.plan(interpretation)
        plan = plans[0]
        assert plan.analysis_type == interpretation.analysis_type
        assert plan.metric == interpretation.metric
        assert plan.period == "2024-Q4"
        PlanValidator(repository).validate(plan)

    def test_adds_the_prior_quarter_when_the_analysis_needs_a_comparison(
        self, interpreter, planner
    ):
        interpretation = interpreter.interpret("How did operating margin change in 2024-Q4?")
        plan = planner.plan(interpretation)[0]
        assert plan.comparison_mode == ComparisonMode.PRIOR_QUARTER

    def test_an_expense_question_is_paired_with_the_margin_consequence(
        self, interpreter, planner
    ):
        interpretation = interpreter.interpret("Why did expenses change in 2024-Q4?")
        types = [plan.analysis_type for plan in planner.plan(interpretation)]
        assert AnalysisType.EXPENSE_VARIANCE in types
        assert AnalysisType.PROFITABILITY in types

    def test_an_unsupported_question_is_rejected_with_guidance(self, interpreter, planner):
        interpretation = interpreter.interpret("What is the weather tomorrow?")
        with pytest.raises(QuestionRejectedError) as error:
            planner.plan(interpretation)
        assert "supported_metrics" in error.value.details


@pytest.fixture(scope="module")
def generator(repository: DatasetRepository) -> RuleBasedExplanationGenerator:
    return RuleBasedExplanationGenerator(repository)


class TestExplanationGenerator:
    def test_every_sentence_is_grounded_in_an_evidence_id(self, generator, evidence_package):
        draft = generator.explain(
            question="Why?",
            interpretation=interpreter_for("operating_margin_pct"),
            evidence=evidence_package,
        )
        assert draft.summary
        assert draft.grounded_on
        assert set(draft.grounded_on) <= set(evidence_package.evidence_ids())

    def test_the_headline_uses_a_figure_from_the_evidence(self, generator, evidence_package):
        draft = generator.explain(
            question="Why?",
            interpretation=interpreter_for("operating_margin_pct"),
            evidence=evidence_package,
        )
        assert "17.13%" in draft.summary
        assert "11.37%" in draft.summary

    def test_findings_do_not_repeat_the_same_fact(self, generator, evidence_package):
        draft = generator.explain(
            question="Why?",
            interpretation=interpreter_for("operating_margin_pct"),
            evidence=evidence_package,
        )
        assert len(draft.findings) == len(set(draft.findings))

    def test_empty_evidence_produces_an_explicit_refusal(self, generator):
        from app.schemas.evidence import EvidencePackage

        draft = generator.explain(
            question="Why?",
            interpretation=interpreter_for("operating_margin_pct"),
            evidence=EvidencePackage(),
        )
        assert "could not" in draft.summary.lower()
        assert draft.grounded_on == ()

    def test_a_missing_comparison_is_never_rendered_as_zero(self, generator):
        """Regression: the headline once said 'from USD 0.00' when absent."""
        from app.models.enums import Direction, Unit
        from app.schemas.evidence import EvidenceItem, EvidencePackage

        evidence = EvidencePackage(
            evidence=[
                EvidenceItem(
                    id="ev_001",
                    metric="revenue",
                    label="Revenue (2024-Q4)",
                    value=13_400_000.0,
                    unit=Unit.CURRENCY,
                    currency="USD",
                    period="2024-Q4",
                    comparison_period="2024-Q3",
                    source_dataset="financial_data",
                    calculation="revenue",
                    direction=Direction.UNKNOWN,
                )
            ]
        )
        draft = generator.explain(
            question="Why?",
            interpretation=interpreter_for("revenue"),
            evidence=evidence,
        )
        assert "from USD 0.00" not in draft.summary
        assert "13,400,000.00" in draft.summary


def interpreter_for(metric_id: str):
    from app.ai.base import Interpretation

    return Interpretation(
        restated_question="test",
        intent="test",
        analysis_type=AnalysisType.PROFITABILITY,
        metric=metric_id,
        period="2024-Q4",
        strategy="test",
        confidence=1.0,
    )


@pytest.fixture(scope="module")
def evidence_package(repository: DatasetRepository):
    from app.analytics.base import AnalysisContext
    from app.models.catalog import resolve_analysis_type
    from app.schemas.analysis import AnalysisPlan
    from app.services.analysis_service import AnalysisService
    from app.services.store import AnalysisStore

    plan = AnalysisPlan(
        analysis_type=AnalysisType.PROFITABILITY,
        metric="operating_margin_pct",
        period="2024-Q4",
        comparison_period="2024-Q3",
    )
    service = AnalysisService.create(repository, AnalysisStore())
    result = service.execute(plan)
    return service.evidence_for([result])


class TestFactories:
    def test_pipeline_uses_the_deterministic_implementations_by_default(
        self, settings, repository
    ):
        pipeline = build_pipeline(settings, repository)
        assert isinstance(pipeline.interpreter, DeterministicQuestionInterpreter)
        assert isinstance(pipeline.planner, DeterministicAnalysisPlanner)
        assert isinstance(pipeline.explainer, RuleBasedExplanationGenerator)
        assert pipeline.llm_enabled is False

    def test_a_provider_without_a_key_does_not_enable_the_llm(self, settings, repository):
        pipeline = build_pipeline(
            settings.model_copy(update={"llm_provider": "openai", "llm_api_key": None}),
            repository,
        )
        assert pipeline.llm_enabled is False

    def test_a_provider_with_a_key_enables_the_llm(self, settings, repository):
        configured = Settings(
            app_env="test",
            llm_provider="openai",
            llm_model="gpt-test",
            llm_api_key="sk-test-not-real",
        )
        pipeline = build_pipeline(configured, repository)
        assert pipeline.llm_enabled is True
        assert pipeline.llm_config.model == "gpt-test"

    def test_require_llm_raises_when_unconfigured(self, settings, repository):
        pipeline = build_pipeline(settings, repository)
        with pytest.raises(Exception):
            require_llm(pipeline.llm_config)

    def test_builders_satisfy_their_interfaces(self, repository):
        assert isinstance(DeterministicQuestionInterpreter(repository), QuestionInterpreter)
        assert isinstance(RuleBasedExplanationGenerator(repository), ExplanationGenerator)
        assert isinstance(DeterministicAnalysisPlanner(repository), AnalysisPlanner)

