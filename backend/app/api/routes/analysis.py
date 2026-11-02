"""Deterministic analysis endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import AnalysisServiceDep
from app.schemas.analysis import AnalysisRequest, AnalysisResult
from app.schemas.evidence import EvidencePackage

router = APIRouter(prefix="/analysis", tags=["analysis"])

AnalysisId = Annotated[
    str,
    Path(min_length=4, max_length=64, pattern=r"^an_[a-f0-9]{4,32}$"),
]


@router.post(
    "",
    response_model=AnalysisResult,
    status_code=status.HTTP_201_CREATED,
    summary="Execute a validated analysis plan",
)
def create_analysis(request: AnalysisRequest, service: AnalysisServiceDep) -> AnalysisResult:
    """Run one deterministic analysis.

    The plan is validated against the metric, dataset and analysis-type catalog
    before any data is read, so an unsupported metric, period, dimension or
    filter is rejected with ``422`` and a machine-readable problem list.
    """
    return service.execute(request.plan, persist=request.persist)


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResult,
    summary="Retrieve a previously executed analysis",
)
def get_analysis(analysis_id: AnalysisId, service: AnalysisServiceDep) -> AnalysisResult:
    return service.get(analysis_id)


@router.get(
    "/{analysis_id}/evidence",
    response_model=EvidencePackage,
    summary="Evidence package for a previously executed analysis",
)
def get_analysis_evidence(
    analysis_id: AnalysisId, service: AnalysisServiceDep
) -> EvidencePackage:
    return service.evidence_for([service.get(analysis_id)])