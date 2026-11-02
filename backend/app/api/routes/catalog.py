"""Catalog capability endpoint.

Exposes the metric catalog and the analysis-type capabilities so the frontend,
and any future planner, can discover what is possible without hard-coding it.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DatasetServiceDep

router = APIRouter(tags=["catalog"])


@router.get("/capabilities", summary="Metrics, analysis types and available dimensions")
def capabilities(service: DatasetServiceDep) -> dict[str, object]:
    return service.capabilities()