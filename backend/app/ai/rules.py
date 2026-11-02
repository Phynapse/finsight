"""Deterministic implementations of the three AI-layer interfaces.

These are the Phase 1 defaults. They use no language model: the question is
matched against the metric catalog's alias table and a small set of intent
keywords, and the explanation is assembled from evidence items by template.

That is a deliberate choice, not a stub. It makes ``POST /questions`` fully
demonstrable and deterministic today, it keeps every number in the answer
traceable to the analytics layer, and it gives the Phase 2 language model a
reference implementation with a fixed contract to match.
"""

from __future__ import annotations

import re

from app.ai.base import ExplanationDraft, Interpretation
from app.core.errors import QuestionRejectedError
from app.data.repository import DatasetRepository
from app.models.catalog import (
    ANALYSIS_TYPE_CATALOG,
    METRIC_CATALOG,
    match_metric_in_text,
    resolve_analysis_type,
    resolve_metric,
)
from app.models.enums import AnalysisType, ComparisonMode, Dimension
from app.schemas.analysis import AnalysisFilter, AnalysisPlan
from app.schemas.evidence import EvidenceItem, EvidencePackage

# ---------------------------------------------------------------------------
# Intent keyword table
# ---------------------------------------------------------------------------
INTENT_RULES: tuple[tuple[AnalysisType, tuple[str, ...], tuple[Dimension, ...]], ...] = (
    (AnalysisType.BUDGET_VARIANCE, ("budget", "overspend", "underspend", "variance", "plan"), ()),
    (AnalysisType.VENDOR_SPEND, ("vendor", "supplier", "third party", "third-party"), ()),
    (AnalysisType.TREND, ("trend", "over time", "history", "trajectory", "growth rate"), ()),
    (
        AnalysisType.PROFITABILITY,
        ("margin", "profitab", "profitable", "ebit", "gross profit"),
        (),
    ),
    (AnalysisType.REVENUE_PERFORMANCE, ("revenue", "sales", "top line", "turnover"), ()),
    (
        AnalysisType.EXPENSE_VARIANCE,
        ("opex", "operating expense", "expense", "spend", "cost", "overhead"),
        (Dimension.CATEGORY),
    ),
)

DIMENSION_KEYWORDS: tuple[tuple[Dimension, tuple[str, ...]], ...] = (
    (Dimension.CATEGORY, ("category", "categories", "spend category")),
    (Dimension.DEPARTMENT, ("department", "departments", "function", "cost centre", "cost center")),
    (Dimension.VENDOR, ("vendor", "supplier")),
    (Dimension.MONTH, ("month", "monthly", "by month")),
)

#: Metrics used in place of an unmatched one when the intent is still clear.
#: Budget questions about statement lines ("operating expenses against budget")
#: are answered against the ledger equivalent, and the substitution is noted in
#: the interpretation rather than made silently.
METRIC_FALLBACKS: dict[AnalysisType, str] = {
    AnalysisType.BUDGET_VARIANCE: "budget_variance",
    AnalysisType.EXPENSE_VARIANCE: "operating_expenses",
    AnalysisType.VENDOR_SPEND: "total_expense",
    AnalysisType.TREND: "total_expense",
}

#: Analysis types whose metric must come from the income statement.
STATEMENT_ANALYSIS = {
    AnalysisType.REVENUE_PERFORMANCE,
    AnalysisType.PROFITABILITY,
    AnalysisType.EXPENSE_VARIANCE,
}

_QUARTER_PATTERN = re.compile(
    r"(?:\b((?:19|20)\d{2})\s*[- ]?\s*)?\bq([1-4])\b", re.IGNORECASE
)
_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
_LAST_QUARTER_PATTERN = re.compile(r"\blast quarter\b|\bprevious quarter\b|\bprior quarter\b", re.IGNORECASE)
_PRIOR_YEAR_PATTERN = re.compile(r"\byear[- ]over[- ]year\b|\byoy\b|\bvs last year\b|\bcompared to last year\b", re.IGNORECASE)


def detect_period(question: str, periods: list[str]) -> tuple[str | None, str | None, str]:
    """Extract a fiscal quarter from free text using explicit rules.

    Returns ``(period, comparison_period, comparison_mode)``. Only periods that
    exist in the dataset are ever returned, so the plan stays valid by
    construction. A year the data does not cover resolves to *no* period rather
    than being silently remapped onto the nearest year that does exist.
    """
    text = question.lower()
    known = list(periods)
    year: int | None = None
    match = _YEAR_PATTERN.search(text)
    if match:
        year = int(match.group(1))

    def prior_year_of(period: str) -> str | None:
        year_text, quarter_text = period.split("-Q")
        prior = f"{int(year_text) - 1}-Q{quarter_text}"
        return prior if prior in known else None

    quarter_match = _QUARTER_PATTERN.search(text)
    if quarter_match:
        target_year = int(quarter_match.group(1)) if quarter_match.group(1) else year
        if target_year is None:
            # No year mentioned: use the most recent year that has this quarter.
            candidates = [period for period in known if period.endswith(f"-Q{quarter_match.group(2)}")]
            if not candidates:
                return None, None, ComparisonMode.NONE.value
            period = candidates[-1]
        else:
            period = f"{target_year}-Q{quarter_match.group(2)}"
        if period not in known:
            return None, None, ComparisonMode.NONE.value
        if _PRIOR_YEAR_PATTERN.search(text):
            prior = prior_year_of(period)
            if prior is not None:
                return period, prior, ComparisonMode.NONE.value
        return period, None, ComparisonMode.NONE.value

    if _LAST_QUARTER_PATTERN.search(text):
        if known:
            period = known[-2] if len(known) > 1 else known[-1]
            return period, None, ComparisonMode.PRIOR_QUARTER.value

    if _PRIOR_YEAR_PATTERN.search(text) and known:
        period = known[-1]
        prior = prior_year_of(period)
        if prior is not None:
            return period, prior, ComparisonMode.NONE.value
    return None, None, ComparisonMode.NONE.value


class DeterministicQuestionInterpreter:
    """Maps a question onto a catalogued metric and analysis type."""

    name = "deterministic_rules"

    def __init__(self, repository: DatasetRepository) -> None:
        self.repository = repository

    def interpret(self, question: str) -> Interpretation:
        text = question.strip()
        lowered = text.lower()

        metric_spec = match_metric_in_text(lowered)
        analysis_type = self._detect_analysis_type(lowered, metric_spec)
        period, comparison_period, comparison_mode = detect_period(lowered, self.repository.periods)
        dimensions = self._detect_dimensions(lowered)
        notes: list[str] = []

        if metric_spec is not None and analysis_type is not None:
            spec = resolve_analysis_type(analysis_type)
            if spec is not None and not spec.supports_metric(metric_spec.id):
                fallback = self._fallback_metric(analysis_type, spec)
                if fallback is not None:
                    notes.append(
                        f"'{metric_spec.label}' is not measured by "
                        f"{spec.label.lower()}; used '{fallback.label}' instead."
                    )
                    metric_spec = fallback

        if period is None and analysis_type in {
            AnalysisType.EXPENSE_VARIANCE,
            AnalysisType.REVENUE_PERFORMANCE,
            AnalysisType.PROFITABILITY,
        }:
            # Fall back to the latest period so the demo always has an answer,
            # and record that we guessed.
            period = self.repository.latest_period
            notes.append(f"No period in the question; defaulted to the latest period {period}.")

        restated = self._restate(text, metric_spec, period)
        intent = self._intent_sentence(analysis_type, metric_spec, period, dimensions)

        confidence = 0.0
        if metric_spec is not None and analysis_type is not None:
            confidence = 0.6 if period else 0.45
        elif metric_spec is not None:
            confidence = 0.3

        return Interpretation(
            restated_question=restated,
            intent=intent,
            analysis_type=analysis_type,
            metric=metric_spec.id if metric_spec else None,
            period=period,
            comparison_period=comparison_period,
            comparison_mode=comparison_mode,
            dimensions=tuple(dimension.value for dimension in dimensions),
            strategy=self.name,
            confidence=confidence,
            notes=tuple(notes),
        )

    # -- helpers ------------------------------------------------------------
    def _detect_analysis_type(self, text: str, metric_spec) -> AnalysisType | None:
        for analysis_type, keywords, _dimensions in INTENT_RULES:
            if any(keyword in text for keyword in keywords):
                spec = resolve_analysis_type(analysis_type)
                if metric_spec is not None and spec is not None:
                    if spec.supports_metric(metric_spec.id):
                        return analysis_type
                    if self._fallback_metric(analysis_type, spec) is not None:
                        return analysis_type
                continue
        if metric_spec is not None:
            spec = resolve_analysis_type(AnalysisType.METRIC_SNAPSHOT)
            if spec is not None and spec.supports_metric(metric_spec.id):
                return AnalysisType.METRIC_SNAPSHOT
        return None

    @staticmethod
    def _fallback_metric(analysis_type: AnalysisType, spec):
        """The metric to measure when the matched metric is out of scope."""
        fallback_id = METRIC_FALLBACKS.get(analysis_type)
        if fallback_id is None:
            return None
        fallback = resolve_metric(fallback_id)
        if fallback is None or not spec.supports_metric(fallback.id):
            return None
        return fallback

    @staticmethod
    def _detect_dimensions(text: str) -> tuple[Dimension, ...]:
        found = [
            dimension
            for dimension, keywords in DIMENSION_KEYWORDS
            if any(keyword in text for keyword in keywords)
        ]
        return tuple(found[:2])

    @staticmethod
    def _restate(question: str, metric_spec, period: str | None) -> str:
        asked = question.rstrip("? ").strip()
        parts = [f"'{asked}'." if asked else "The question as asked."]
        if metric_spec is not None:
            parts.append(f"FinSight matched the metric '{metric_spec.label}'.")
        if period:
            parts.append(f"The analysis period is {period}.")
        return " ".join(parts)

    @staticmethod
    def _intent_sentence(
        analysis_type: AnalysisType | None,
        metric_spec,
        period: str | None,
        dimensions: tuple[Dimension, ...],
    ) -> str:
        if analysis_type is None or metric_spec is None:
            return (
                "The question does not map onto a catalogued financial metric, so no "
                "deterministic analysis can be planned."
            )
        spec = resolve_analysis_type(analysis_type)
        label = spec.label if spec else analysis_type.value
        grouping = f" grouped by {', '.join(dimensions)}" if dimensions else ""
        scope = f" for {period}" if period else " across all available periods"
        return f"Run {label.lower()} on {metric_spec.label.lower()}{scope}{grouping}."


class DeterministicAnalysisPlanner:
    """Builds closed-form analysis plans from an interpretation."""

    name = "deterministic_rules"

    def __init__(self, repository: DatasetRepository) -> None:
        self.repository = repository

    def plan(self, interpretation: Interpretation) -> list[AnalysisPlan]:
        if interpretation.analysis_type is None or interpretation.metric is None:
            raise QuestionRejectedError(
                "The question does not map onto a supported financial analysis.",
                details={
                    "supported_metrics": list(METRIC_CATALOG),
                    "supported_analysis_types": [item.value for item in ANALYSIS_TYPE_CATALOG],
                },
            )

        spec = resolve_analysis_type(interpretation.analysis_type)
        if spec is None:  # pragma: no cover - interpretation is catalog-derived
            raise QuestionRejectedError(details={"analysis_type": interpretation.analysis_type})

        dimensions = [
            Dimension(value)
            for value in interpretation.dimensions
            if spec.supports_dimension(Dimension(value))
        ]

        # "Why did X increase in Q3?" means "compared with the quarter before".
        # If the question named a period but no comparison, and the analysis
        # type needs one, default to the prior quarter.
        comparison_mode = ComparisonMode(interpretation.comparison_mode)
        if (
            interpretation.comparison_period is None
            and comparison_mode is ComparisonMode.NONE
            and spec.requires_comparison
            and interpretation.period
        ):
            comparison_mode = spec.default_comparison

        plan = AnalysisPlan(
            analysis_type=interpretation.analysis_type,
            metric=interpretation.metric,
            period=interpretation.period,
            comparison_period=interpretation.comparison_period,
            comparison_mode=comparison_mode,
            dimensions=dimensions[:1] if spec.allowed_dimensions else [],
            filters=self._filters(dimensions),
            limit=min(10, spec.max_breakdown_items),
        )
        plans = [plan]

        # A "why" question about expense deserves the margin consequence too.
        if interpretation.analysis_type is AnalysisType.EXPENSE_VARIANCE and interpretation.period:
            if resolve_analysis_type(AnalysisType.PROFITABILITY) is not None:
                plans.append(
                    AnalysisPlan(
                        analysis_type=AnalysisType.PROFITABILITY,
                        metric="operating_income",
                        period=interpretation.period,
                        comparison_mode=ComparisonMode.PRIOR_QUARTER,
                    )
                )
        return plans

    @staticmethod
    def _filters(dimensions: tuple[Dimension, ...]) -> list[AnalysisFilter]:
        # Dimension keywords only steer grouping; filters stay empty until a
        # question names an actual department or category value.
        return []


class RuleBasedExplanationGenerator:
    """Assembles an explanation from evidence items only.

    Every sentence is built from a value that exists in the evidence package,
    and every evidence item used is recorded in ``grounded_on``. When a real
    language model is wired in, it receives the same package and is held to the
    same rule.
    """

    name = "rule_based_templates"
    model: str | None = None

    def __init__(self, repository: DatasetRepository) -> None:
        self.repository = repository

    def explain(
        self,
        *,
        question: str,
        interpretation: Interpretation,
        evidence: EvidencePackage,
    ) -> ExplanationDraft:
        if evidence.is_empty:
            return ExplanationDraft(
                summary=(
                    "FinSight could not produce evidence for this question with the data "
                    "currently loaded."
                ),
                provider=self.name,
                model=self.model,
            )

        currency = self.repository.currency()
        summary_parts: list[str] = []
        findings: list[str] = []
        grounded: list[str] = []

        headline = self._headline(evidence, interpretation, currency)
        if headline:
            summary_parts.append(headline[0])
            grounded.append(headline[1])

        drivers = self._drivers(evidence)
        for sentence, evidence_id in drivers:
            findings.append(sentence)
            grounded.append(evidence_id)

        caveat = self._caveat(interpretation, evidence)
        if caveat:
            findings.append(caveat)

        return ExplanationDraft(
            summary=" ".join(summary_parts) or "Evidence was produced; see the items below.",
            detail=(
                "This explanation was assembled from the evidence items by template. "
                "It does not introduce any figure that is not listed in the evidence."
            ),
            findings=tuple(findings),
            grounded_on=tuple(dict.fromkeys(grounded)),
            provider=self.name,
            model=self.model,
        )

    # -- template helpers ---------------------------------------------------
    @staticmethod
    def _format(value: float, currency: str, unit: str) -> str:
        """Render an evidence value with the right unit suffix."""
        if unit == "percent":
            return f"{value:,.2f}%"
        if unit == "count":
            return f"{value:,.0f}"
        if unit == "ratio":
            return f"{value:,.2f}"
        return f"{currency} {value:,.2f}"

    def _headline(
        self, evidence: EvidencePackage, interpretation: Interpretation, currency: str
    ) -> tuple[str, str] | None:
        item = self._headline_item(evidence, interpretation.metric)
        if item is None:
            return None

        label = item.label.split(" (")[0]
        value = self._format(item.value, item.currency or currency, item.unit.value)
        period = item.period or "the selected period"

        if item.comparison_value is None:
            if item.percentage_change is None and item.change is not None:
                movement = self._format(abs(item.change), item.currency or currency, item.unit.value)
                verb = "rose" if item.change > 0 else "fell"
                return (
                    f"{label} {verb} by {movement} to {value} in {period}.",
                    item.id,
                )
            return (f"{label} stands at {value} for {period}.", item.id)

        comparison = self._format(
            item.comparison_value, item.currency or currency, item.unit.value
        )
        comparison_period = item.comparison_period or "the comparison period"
        verb = "rose" if item.value >= item.comparison_value else "fell"
        if item.percentage_change is not None:
            verb = f"{verb} by {abs(item.percentage_change):.2f}%"
        return (
            f"{label} {verb} to {value} in {period} from "
            f"{comparison} in {comparison_period}.",
            item.id,
        )

    @staticmethod
    def _headline_item(evidence: EvidencePackage, metric_id: str | None) -> EvidenceItem | None:
        """Choose the one evidence item that best states the metric's level.

        Preference order: an item whose label is the catalogued metric label
        (a metric-level fact rather than a dimensional row), then an item that
        already carries its own comparison so the headline can state movement
        without a second lookup. Ties keep the earliest item, which is the
        metric-level fact the analytics layer emitted first.
        """
        if not metric_id:
            return None
        candidates = [item for item in evidence.evidence if item.metric == metric_id]
        if not candidates:
            return None
        spec = resolve_metric(metric_id)

        def rank(item: EvidenceItem) -> tuple[int, int]:
            unnamed = 0 if spec is not None and item.label.startswith(spec.label) else 1
            uncompared = 0 if item.comparison_value is not None else 1
            return (unnamed, uncompared)

        return min(candidates, key=rank)

    @staticmethod
    def _drivers(evidence: EvidencePackage) -> list[tuple[str, str]]:
        movements = [item for item in evidence.evidence if item.change is not None]
        movements.sort(key=lambda item: abs(item.change or 0.0), reverse=True)
        sentences: list[tuple[str, str]] = []
        seen: set[tuple[str, str | None, float]] = set()
        for item in movements:
            fact = (item.metric, item.period, round(item.change or 0.0, 2))
            if fact in seen:
                continue
            seen.add(fact)
            change = item.change or 0.0
            direction = "increased" if change >= 0 else "decreased"
            share = (
                f", which is {item.contribution_to_change_pct:.1f}% of the total movement"
                if item.contribution_to_change_pct is not None
                else ""
            )
            if item.percentage_change is None:
                magnitude = f"{abs(change):,.2f}"
            else:
                magnitude = f"{abs(item.percentage_change):.2f}% ({change:+,.2f})"
            sentences.append(
                (
                    f"{item.label.split(' (')[0]} {direction} by {magnitude}{share}.",
                    item.id,
                )
            )
            if len(sentences) == 3:
                break
        return sentences

    @staticmethod
    def _caveat(interpretation: Interpretation, evidence: EvidencePackage) -> str | None:
        if interpretation.strategy != "deterministic_rules":
            return None
        if not evidence.periods_covered:
            return None
        return (
            "Scope: "
            + ", ".join(evidence.periods_covered)
            + ". Attribution covers ledger movements only; it does not infer intent."
        )