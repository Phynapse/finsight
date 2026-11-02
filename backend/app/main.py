"""FinSight application entry point.

    uvicorn app.main:app --reload

The app factory keeps construction explicit: settings, the dataset repository
and every service are built in :class:`app.container.AppContainer` and injected
through dependencies. Tests call the same factory with test settings.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import analysis, catalog, datasets, questions, system
from app.container import AppContainer
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger, get_request_id
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.schemas.common import ErrorDetail, ErrorResponse

logger = get_logger(__name__)

DESCRIPTION = """
FinSight answers business and financial questions against a controlled dataset.

**The boundary that matters:** a language model interprets the question and
explains the result. Python and Pandas do all arithmetic. Every figure in a
response arrives with its source dataset and its formula, and no model output
is ever trusted without passing the same validation as an HTTP client.

Synthetic data only. No real company financials are included.
"""


def error_response(error: AppError, status_code: int | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code or error.status_code,
        content={"error": ErrorDetail(**error.to_payload()).model_dump(mode="json")},
        headers={"X-Request-ID": get_request_id() or "-"},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FinSight ASGI application."""
    resolved = settings or get_settings()
    configure_logging(resolved.log_level, resolved.log_json)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        container = AppContainer.create(resolved)
        container.load_datasets()
        application.state.container = container
        logger.info(
            "FinSight %s ready: %s datasets, api prefix %s, llm %s",
            resolved.app_version,
            container.repository.dataset_count,
            resolved.api_prefix,
            "enabled" if container.pipeline.llm_enabled else "disabled",
        )
        try:
            yield
        finally:
            application.state.container = None
            logger.info("FinSight shut down cleanly")

    application = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Middleware runs bottom-up: body limit, then CORS, then request context.
    application.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=resolved.max_request_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origin_list),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        max_age=600,
    )
    application.add_middleware(RequestContextMiddleware)

    prefix = resolved.api_prefix.rstrip("/")
    application.include_router(system.router, prefix=prefix)
    application.include_router(catalog.router, prefix=prefix)
    application.include_router(datasets.router, prefix=prefix)
    application.include_router(analysis.router, prefix=prefix)
    application.include_router(questions.router, prefix=prefix)

    _register_error_handlers(application)
    return application


def _register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
        level = logger.warning if error.status_code < 500 else logger.error
        level(
            "request failed: %s %s", request.method, request.url.path, exc_info=error
        )
        return error_response(error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Return a sanitised validation payload.

        The offending input is deliberately not echoed back: it can be large,
        and it can contain anything the client sent.
        """
        problems = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ())[1:]) or "body",
                "message": str(item.get("msg", "invalid value")),
                "type": str(item.get("type", "value_error")),
            }
            for item in error.errors()[:20]
        ]
        app_error = AppError(
            "The request payload is not valid.",
            details={"problems": problems},
            code="request_validation_failed",
        )
        app_error.status_code = 422  # type: ignore[misc]
        return error_response(app_error, status_code=422)

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}
        app_error = AppError(
            str(error.detail) if error.detail else "The request could not be completed.",
            code=codes.get(error.status_code, "http_error"),
        )
        return error_response(app_error, status_code=error.status_code)

    @application.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> JSONResponse:
        """Last resort: log the detail, tell the client nothing."""
        logger.exception("unhandled error", extra={"path": request.url.path})
        return error_response(
            AppError(
                "An unexpected error occurred. The incident has been logged.",
                code="internal_error",
            ),
            status_code=500,
        )


app = create_app()