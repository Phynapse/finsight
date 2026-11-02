"""Shared response contracts: errors and health."""

from __future__ import annotations

from pydantic import Field

from app.schemas.analysis import _StrictModel


class ErrorDetail(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(_StrictModel):
    """The single error shape returned by every endpoint.

    Never contains a traceback, a file path, or a raw exception string.
    """

    error: ErrorDetail


class HealthResponse(_StrictModel):
    status: str = Field(description="'ok' or 'degraded'.")
    service: str
    version: str
    environment: str
    uptime_seconds: float
    checks: dict[str, str] = Field(default_factory=dict)
    datasets_loaded: int = 0
    llm_enabled: bool = False


class RootResponse(_StrictModel):
    """Service banner returned by ``GET /``."""

    service: str
    version: str
    description: str
    api_prefix: str
    docs_url: str
    endpoints: dict[str, str] = Field(default_factory=dict)