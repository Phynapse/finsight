"""Dataset discovery endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import DatasetServiceDep
from app.schemas.dataset_api import DatasetListResponse, DatasetSummary

router = APIRouter(prefix="/datasets", tags=["datasets"])

DatasetId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=40,
        pattern=r"^[a-z_]+$",
        description="Dataset id from the catalog, for example 'transactions'.",
    ),
]


@router.get("", response_model=DatasetListResponse, summary="List bundled datasets")
def list_datasets(service: DatasetServiceDep) -> DatasetListResponse:
    return service.list_datasets()


@router.get(
    "/{dataset_id}/summary",
    response_model=DatasetSummary,
    summary="Metadata and integrity checks for one dataset",
)
def dataset_summary(dataset_id: DatasetId, service: DatasetServiceDep) -> DatasetSummary:
    return service.summary(dataset_id)


@router.get("/{dataset_id}/integrity", summary="Cross-dataset integrity checks")
def dataset_integrity(dataset_id: DatasetId, service: DatasetServiceDep) -> dict[str, object]:
    service.summary(dataset_id)  # 404s for an unknown dataset
    return service.integrity_report()


@router.get(
    "/available/periods",
    summary="Fiscal periods available for analysis",
)
def available_periods(
    service: DatasetServiceDep,
    include_months: Annotated[bool, Query(description="Also return ledger month keys.")] = False,
) -> dict[str, object]:
    capabilities = service.capabilities()
    payload: dict[str, object] = {"periods": capabilities["periods"]}
    if include_months:
        payload["months"] = capabilities["months"]
    return payload