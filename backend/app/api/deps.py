"""FastAPI dependencies.

Routes receive services through these providers, so no route touches the
repository, the filesystem or a Pandas frame directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.container import AppContainer
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.question_service import QuestionService


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - only possible if startup was skipped
        raise RuntimeError("Application container is not initialised.")
    return container


Container = Annotated[AppContainer, Depends(get_container)]


def get_dataset_service(container: Container) -> DatasetService:
    return container.dataset_service


def get_analysis_service(container: Container) -> AnalysisService:
    return container.analysis_service


def get_question_service(container: Container) -> QuestionService:
    return container.question_service


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
QuestionServiceDep = Annotated[QuestionService, Depends(get_question_service)]