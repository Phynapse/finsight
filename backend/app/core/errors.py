"""Typed application errors and the sanitised error contract.

Raw exceptions never reach a client. Every expected failure raises an
:class:`AppError` with a stable machine-readable ``code``, and the global
handlers in :mod:`app.main` render it into the :class:`ErrorResponse` schema.
Unexpected exceptions are logged server-side and reported as a generic
``internal_error`` so stack traces, file paths and SQL fragments cannot leak.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every error FinSight is willing to tell a client about."""

    code: str = "app_error"
    status_code: int = 500
    default_message: str = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = details or {}
        if code:
            self.code = code
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ConfigurationError(AppError):
    code = "configuration_error"
    status_code = 500
    default_message = "The service is misconfigured."


class DatasetNotFoundError(AppError):
    code = "dataset_not_found"
    status_code = 404
    default_message = "The requested dataset does not exist."


class DatasetValidationError(AppError):
    code = "dataset_validation_failed"
    status_code = 500
    default_message = "A bundled dataset failed integrity validation."


class UnknownMetricError(AppError):
    code = "unknown_metric"
    status_code = 422
    default_message = "The requested metric is not defined in the metric catalog."


class UnknownAnalysisTypeError(AppError):
    code = "unsupported_analysis_type"
    status_code = 422
    default_message = "The requested analysis type is not supported."


class InvalidPeriodError(AppError):
    code = "invalid_period"
    status_code = 422
    default_message = "The requested period is not present in the dataset."


class InvalidFilterError(AppError):
    code = "invalid_filter"
    status_code = 422
    default_message = "The requested filter is not supported for this analysis."


class PlanValidationError(AppError):
    """Aggregates every plan problem so a client sees all of them at once."""

    code = "invalid_analysis_plan"
    status_code = 422
    default_message = "The analysis plan is not valid."


class NoDataForPlanError(AppError):
    code = "no_data_for_plan"
    status_code = 422
    default_message = "The analysis plan is valid but no data matches it."


class AnalysisNotFoundError(AppError):
    code = "analysis_not_found"
    status_code = 404
    default_message = "The requested analysis does not exist or has expired."


class AnalysisExecutionError(AppError):
    code = "analysis_execution_failed"
    status_code = 500
    default_message = "The analysis could not be completed."


class QuestionRejectedError(AppError):
    code = "question_rejected"
    status_code = 422
    default_message = "The question could not be answered from the available datasets."


class PayloadTooLargeError(AppError):
    code = "payload_too_large"
    status_code = 413
    default_message = "The request body exceeds the configured size limit."


class LLMNotConfiguredError(AppError):
    code = "llm_not_configured"
    status_code = 503
    default_message = "No LLM provider is configured; only deterministic analysis is available."


class LLMProviderError(AppError):
    code = "llm_provider_error"
    status_code = 502
    default_message = "The LLM provider failed to return a usable response."