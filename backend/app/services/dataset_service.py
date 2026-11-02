"""Dataset discovery: what data FinSight has, and whether it is trustworthy."""

from __future__ import annotations

from app.core.errors import DatasetNotFoundError
from app.core.logging import get_logger
from app.data.repository import DatasetRepository
from app.models.catalog import dataset_ids, resolve_dataset
from app.models.enums import AnalysisType, Dimension
from app.schemas.dataset_api import DatasetListResponse, DatasetSummary

logger = get_logger(__name__)


class DatasetService:
    """Read-only view over the bundled datasets and their catalog metadata."""

    def __init__(self, repository: DatasetRepository) -> None:
        self.repository = repository

    def list_datasets(self) -> DatasetListResponse:
        summaries = [self.repository.summary(dataset_id) for dataset_id in dataset_ids()]
        return DatasetListResponse(datasets=summaries, total=len(summaries))

    def summary(self, dataset_id: str) -> DatasetSummary:
        if resolve_dataset(dataset_id) is None or not self.repository.has(dataset_id):
            raise DatasetNotFoundError(
                details={"dataset_id": dataset_id, "available": list(dataset_ids())}
            )
        return self.repository.summary(dataset_id)

    def integrity_report(self) -> dict[str, object]:
        checks = self.repository.integrity_checks()
        return {
            "passed": all(check.passed for check in checks),
            "total": len(checks),
            "failed": [check.id for check in checks if not check.passed],
        }

    def capabilities(self) -> dict[str, object]:
        """Everything a UI or a future planner needs to know what is possible."""
        from app.models.catalog import METRIC_CATALOG

        return {
            "metrics": [
                {
                    "id": spec.id,
                    "label": spec.label,
                    "unit": spec.unit.value,
                    "source_dataset": spec.source_dataset,
                    "formula": spec.formula,
                    "description": spec.description,
                }
                for spec in METRIC_CATALOG.values()
            ],
            "analysis_types": [
                {
                    "id": spec.id.value,
                    "label": spec.label,
                    "description": spec.description,
                    "required_datasets": list(spec.required_datasets),
                    "supported_metrics": list(spec.supported_metrics),
                    "allowed_dimensions": [dimension.value for dimension in spec.allowed_dimensions],
                    "allowed_filters": list(spec.allowed_filters),
                    "default_comparison": spec.default_comparison.value,
                }
                for spec in _analysis_specs()
            ],
            "dimensions": [dimension.value for dimension in Dimension],
            "periods": self.repository.periods,
            "months": self.repository.months,
            "departments": self.repository.departments(),
            "categories": self.repository.categories(),
            "currency": self.repository.currency(),
        }


def _analysis_specs():
    from app.models.catalog import ANALYSIS_TYPE_CATALOG

    return list(ANALYSIS_TYPE_CATALOG.values())


def supported_analysis_types() -> tuple[AnalysisType, ...]:
    return tuple(_analysis_specs())