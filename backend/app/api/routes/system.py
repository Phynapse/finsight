"""Health and service banner endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import Container
from app.schemas.common import HealthResponse, RootResponse

router = APIRouter(tags=["system"])

DESCRIPTION = (
    "FinSight - AI financial intelligence platform. "
    "Every financial figure is computed deterministically in Python; "
    "a language model interprets questions and explains evidence."
)


@router.get("/", response_model=RootResponse, summary="Service banner")
def root(container: Container) -> RootResponse:
    prefix = container.settings.api_prefix
    return RootResponse(
        service=container.settings.app_name,
        version=container.settings.app_version,
        description=DESCRIPTION,
        api_prefix=prefix,
        docs_url="/docs",
        endpoints={
            "health": f"{prefix}/health",
            "capabilities": f"{prefix}/capabilities",
            "datasets": f"{prefix}/datasets",
            "dataset_summary": f"{prefix}/datasets/{{dataset_id}}/summary",
            "analysis": f"{prefix}/analysis",
            "analysis_status": f"{prefix}/analysis/{{analysis_id}}",
            "questions": f"{prefix}/questions",
        },
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness and readiness")
def health(container: Container) -> HealthResponse:
    repository = container.repository
    datasets_loaded = repository.dataset_count if repository.is_loaded else 0
    integrity_ok = repository.integrity_ok() if repository.is_loaded else False

    checks = {
        "datasets_loaded": "ok" if datasets_loaded else "failed",
        "data_integrity": "ok" if integrity_ok else "failed",
        "analysis_registry": "ok",
        "llm_provider": "configured" if container.pipeline.llm_enabled else "disabled",
    }
    degraded = datasets_loaded == 0 or not integrity_ok
    result = HealthResponse(
        status="degraded" if degraded else "ok",
        service=container.settings.app_name,
        version=container.settings.app_version,
        environment=container.settings.app_env,
        uptime_seconds=container.uptime_seconds,
        checks=checks,
        datasets_loaded=datasets_loaded,
        llm_enabled=container.pipeline.llm_enabled,
    )
    response = JSONResponse(content=result.model_dump(mode="json"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response  # type: ignore[return-value]