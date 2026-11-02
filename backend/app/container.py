"""Application wiring.

A single :class:`AppContainer` holds the process-wide singletons. It is created
once at startup, injected into routes through FastAPI dependencies, and
constructed explicitly in tests, so nothing depends on import order or global
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.ai.factory import AIPipeline, build_pipeline
from app.core.config import Settings, get_settings
from app.core.errors import DatasetValidationError
from app.core.logging import configure_logging, get_logger
from app.data.repository import DatasetRepository
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.question_service import QuestionService
from app.services.store import AnalysisStore

logger = get_logger(__name__)


@dataclass
class AppContainer:
    """Owns the dataset repository and every service built on top of it."""

    settings: Settings
    repository: DatasetRepository
    store: AnalysisStore
    dataset_service: DatasetService
    analysis_service: AnalysisService
    question_service: QuestionService
    pipeline: AIPipeline
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(cls, settings: Settings | None = None) -> AppContainer:
        resolved = settings or get_settings()
        configure_logging(resolved.log_level, resolved.log_json)

        repository = DatasetRepository(data_dir=resolved.resolved_data_dir)
        store = AnalysisStore(
            max_items=resolved.analysis_store_max_items,
            ttl_seconds=resolved.analysis_store_ttl_seconds,
        )
        dataset_service = DatasetService(repository)
        analysis_service = AnalysisService.create(repository, store)
        pipeline = build_pipeline(resolved, repository)
        question_service = QuestionService(repository, analysis_service, pipeline)

        return cls(
            settings=resolved,
            repository=repository,
            store=store,
            dataset_service=dataset_service,
            analysis_service=analysis_service,
            question_service=question_service,
            pipeline=pipeline,
        )

    def load_datasets(self) -> None:
        """Load and validate every bundled dataset, failing fast on bad data."""
        if self.repository.is_loaded:
            return
        self.repository.load()
        report = self.dataset_service.integrity_report()
        if not report["passed"]:
            raise DatasetValidationError(
                "Bundled datasets failed cross-dataset integrity checks.",
                details={"failed_checks": report["failed"], "total": report["total"]},
            )
        logger.info(
            "%s datasets loaded, %s integrity checks passed",
            report["total"],
            self.repository.dataset_count,
        )

    @property
    def uptime_seconds(self) -> float:
        return round((datetime.now(timezone.utc) - self.started_at).total_seconds(), 3)