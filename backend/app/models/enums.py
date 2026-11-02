"""Domain enums shared by the catalog, analytics layer and API schemas."""

from __future__ import annotations

from enum import StrEnum


class Currency(StrEnum):
    USD = "USD"


class Unit(StrEnum):
    """Physical meaning of a metric value."""

    CURRENCY = "currency"
    PERCENT = "percent"
    COUNT = "count"
    RATIO = "ratio"


class Direction(StrEnum):
    """Whether a value moved up or down against its comparison."""

    INCREASE = "increase"
    DECREASE = "decrease"
    FLAT = "flat"
    UNKNOWN = "unknown"


class AnalysisType(StrEnum):
    """The closed set of deterministic analyses the platform can execute."""

    METRIC_SNAPSHOT = "metric_snapshot"
    REVENUE_PERFORMANCE = "revenue_performance"
    EXPENSE_ANALYSIS = "expense_analysis"
    EXPENSE_VARIANCE = "expense_variance"
    PROFITABILITY = "profitability"
    BUDGET_VARIANCE = "budget_variance"
    VENDOR_SPEND = "vendor_spend"
    TREND = "trend"


class ComparisonMode(StrEnum):
    """How the comparison period is derived from the requested period."""

    NONE = "none"
    PRIOR_QUARTER = "prior_quarter"
    PRIOR_YEAR = "prior_year"


class AnalysisStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_FOUND = "not_found"


class AnswerStatus(StrEnum):
    """Lifecycle of a natural-language question."""

    ANSWERED = "answered"
    PARTIALLY_ANSWERED = "partially_answered"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class Granularity(StrEnum):
    QUARTER = "quarter"
    MONTH = "month"
    VENDOR = "vendor"


class TransactionType(StrEnum):
    EXPENSE = "expense"
    CREDIT = "credit"


class Dimension(StrEnum):
    """Dimensions an analysis may group by.

    Grouping is always by an allow-listed enum, never by an arbitrary column
    name supplied by a caller or by a language model.
    """

    DEPARTMENT = "department"
    CATEGORY = "category"
    VENDOR = "vendor"
    MONTH = "month"
    QUARTER = "quarter"