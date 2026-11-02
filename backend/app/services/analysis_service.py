"""Analysis orchestration: validate a plan, run it, package the evidence."""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.base import (
    AnalysisContext,
    Timer,
    build_result,
    new_analysis_id,
)
from app.analytics.factory import build_registry
from app.analytics.validator import PlanValidator
from app.analytics.base import AnalyzerRegistry
from app.core.errors import AnalysisExecutionError, AppError
from app.core.logging import get_logger
from app.data.repository import DatasetRepository
from app.models.catalog import METRIC_CATALOG, resolve_analysis_type, resolve_metric
from app.models.enums import Direction, Unit
from app.schemas.analysis import AnalysisPlan, AnalysisResult, DimensionValue
from app.schemas.evidence import EvidenceItem, EvidencePackage
from app.services.store import AnalysisStore

logger = get_logger(__name__)


@dataclass
class AnalysisService:
    """Executes validated analysis plans against the in-memory repository."""

    repository: DatasetRepository
    store: AnalysisStore
    registry: AnalyzerRegistry
    validator: PlanValidator

    @classmethod
    def create(cls, repository: DatasetRepository, store: AnalysisStore) -> AnalysisService:
        return cls(
            repository=repository,
            store=store,
            registry=build_registry(),
            validator=PlanValidator(repository),
        )

    # -- execution ----------------------------------------------------------
    def execute(self, plan: AnalysisPlan, *, persist: bool = True) -> AnalysisResult:
        """Validate and run a plan. Raises a typed :class:`AppError` on failure."""
        self.validator.validate(plan)

        spec = resolve_analysis_type(plan.analysis_type)
        if spec is None:  # pragma: no cover - the validator already rejects this
            raise AnalysisExecutionError(
                f"Unknown analysis type '{plan.analysis_type}'.", details={"plan": plan.model_dump()}
            )

        context = AnalysisContext(repository=self.repository, plan=plan, spec=spec)
        timer = Timer()
        try:
            output = self.registry.get(plan.analysis_type).run(context)
        except AppError:
            raise
        except Exception as error:  # pragma: no cover - defensive, never leaks details
            logger.exception("analysis execution failed", extra={"analysis_type": spec.id})
            raise AnalysisExecutionError(
                "The analysis could not be completed.",
                details={"analysis_type": spec.id, "reason": type(error).__name__},
            ) from error

        result = build_result(
            analysis_id=new_analysis_id(),
            plan=plan,
            context=context,
            output=output,
            datasets_used=spec.required_datasets or (plan_metric_dataset(plan),),
            duration_ms=timer.elapsed_ms(),
        )
        if persist:
            self.store.put(result.analysis_id, result)
        logger.info(
            "analysis %s completed in %sms (%s rows)",
            result.analysis_id,
            result.duration_ms,
            result.row_count,
        )
        return result

    def get(self, analysis_id: str) -> AnalysisResult:
        return self.store.get(analysis_id)

    # -- evidence -----------------------------------------------------------
    def evidence_for(self, results: list[AnalysisResult]) -> EvidencePackage:
        """Convert analysis results into the bounded evidence package.

        This is the boundary the explanation layer is allowed to read from: if a
        fact is not in this package, no explanation may state it.
        """
        evidence: list[EvidenceItem] = []
        datasets: list[str] = []
        periods: list[str] = []
        counter = 0

        def next_id() -> str:
            nonlocal counter
            counter += 1
            return f"ev_{counter:03d}"

        for result in results:
            datasets.extend(result.datasets_used)
            for period in (result.period, result.comparison_period):
                if period and period not in periods:
                    periods.append(period)

            metric_spec = resolve_metric(result.metric)
            unit = metric_spec.unit if metric_spec else Unit.CURRENCY
            metric_currency = self.repository.currency() if unit is Unit.CURRENCY else None
            source_dataset = metric_spec.source_dataset if metric_spec else ""
            source_fields = list(metric_spec.source_fields) if metric_spec else []
            breakdown_limit = max(1, result.plan.limit)
            reported: set[tuple[str, float]] = set()

            for metric in result.metrics:
                comparison_period = metric.comparison_period or result.comparison_period
                evidence.append(
                    EvidenceItem(
                        id=next_id(),
                        metric=metric.id,
                        label=f"{metric.label} ({metric.period or 'all periods'})",
                        value=metric.value,
                        unit=metric.unit,
                        currency=metric.currency,
                        period=metric.period,
                        comparison_period=comparison_period,
                        comparison_value=metric.comparison_value,
                        change=metric.change,
                        percentage_change=metric.percentage_change,
                        direction=direction_of(metric.value, metric.comparison_value),
                        source_dataset=metric.source_dataset,
                        source_fields=list(metric_spec.source_fields) if metric_spec else [],
                        calculation=metric.calculation,
                        is_derived=bool(metric.formula_inputs) or "=" in metric.calculation,
                    )
                )

            for row in self._breakdown_rows(result)[:breakdown_limit]:
                row_metric = row.metric or result.metric
                row_spec = resolve_metric(row_metric)
                row_unit = row_spec.unit if row_spec else unit
                row_currency = metric_currency if row_unit is Unit.CURRENCY else None
                reported.add((row.key, row.value))
                evidence.append(
                    EvidenceItem(
                        id=next_id(),
                        metric=row_metric,
                        label=f"{row.label or row.key} ({result.period or 'all periods'})"[:160],
                        value=row.value,
                        unit=row_unit,
                        currency=row_currency,
                        period=result.period,
                        comparison_period=result.comparison_period,
                        comparison_value=row.comparison_value,
                        change=row.change,
                        percentage_change=row.percentage_change,
                        direction=direction_of(row.value, row.comparison_value),
                        share_of_total_pct=row.share_of_total_pct,
                        contribution_to_change_pct=row.contribution_to_change_pct,
                        source_dataset=(
                            row_spec.source_dataset if row_spec else source_dataset
                        ),
                        source_fields=list(row_spec.source_fields) if row_spec else source_fields,
                        calculation=(
                            f"{row.dimension.value} '{row.key}': "
                            f"{'net spend (expense - credit)' if row_unit is Unit.CURRENCY else 'value'} "
                            "for the period"
                        ),
                    )
                )

            series_spec = resolve_metric(result.metric) or metric_spec
            series_unit = series_spec.unit if series_spec else unit
            series_label = series_spec.label if series_spec else result.metric
            for point in result.series:
                if (point.key, point.value) in reported:
                    continue
                reported.add((point.key, point.value))
                evidence.append(
                    EvidenceItem(
                        id=next_id(),
                        metric=result.metric,
                        label=f"{series_label} {point.key}"[:160],
                        value=point.value,
                        unit=series_unit,
                        currency=metric_currency if series_unit is Unit.CURRENCY else None,
                        period=point.key,
                        comparison_value=point.comparison_value,
                        change=point.change,
                        percentage_change=point.percentage_change,
                        direction=direction_of(point.value, point.comparison_value),
                        source_dataset=source_dataset,
                        source_fields=source_fields,
                        calculation="time series point read from the source dataset",
                    )
                )

        return EvidencePackage(
            evidence=evidence[:200],
            datasets_used=sorted({item for item in datasets if item}),
            periods_covered=periods,
            notes=[f"{len(evidence)} evidence item(s) from {len(results)} analysis run(s)"],
        )

    @staticmethod
    def _breakdown_rows(result: AnalysisResult) -> list[DimensionValue]:
        """Every breakdown row is evidence, compared or not.

        An uncompared row is still a fact an explanation may cite (a level, a
        share of total); its missing comparison simply means no movement is
        claimed for it.
        """
        return list(result.breakdown)


def plan_metric_dataset(plan: AnalysisPlan) -> str:
    metric = resolve_metric(plan.metric)
    return metric.source_dataset if metric else "unknown"


def direction_of(current: float, previous: float | None, tolerance: float = 0.01) -> str:
    if previous is None:
        return Direction.UNKNOWN.value
    change = current - previous
    if change > tolerance:
        return Direction.INCREASE.value
    if change < -tolerance:
        return Direction.DECREASE.value
    return Direction.FLAT.value


def catalogued_metrics() -> tuple[str, ...]:
    return tuple(METRIC_CATALOG)