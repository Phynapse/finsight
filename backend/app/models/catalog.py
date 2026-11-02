"""The metric / dataset / analysis-type catalog.

This module is the single source of truth for *what FinSight is allowed to
ask the data for*. It is deliberately declarative: every analyzer declares its
own capabilities here, and the plan validator refuses anything that is not
declared. Nothing here imports the analytics layer, so the catalog can be read
(and tested) without loading a single DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.models.enums import AnalysisType, ComparisonMode, Dimension, Granularity, Unit

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Metadata for one bundled CSV dataset."""

    id: str
    label: str
    filename: str
    description: str
    grain: str
    primary_key: tuple[str, ...]
    row_grain_label: str
    expected_min_rows: int = 1


DATASET_CATALOG: Mapping[str, DatasetSpec] = {
    spec.id: spec
    for spec in (
        DatasetSpec(
            id="financial_data",
            label="Income statement",
            filename="financial_data.csv",
            description=(
                "Quarterly income statement and cash roll-forward for FY2023 and "
                "FY2024. One row per fiscal quarter."
            ),
            grain="quarter",
            primary_key=("period",),
            row_grain_label="fiscal quarter",
            expected_min_rows=8,
        ),
        DatasetSpec(
            id="transactions",
            label="Operating expense ledger",
            filename="transactions.csv",
            description=(
                "FY2024 operating expense ledger. One row per expense or credit "
                "memo, including non-cash charges."
            ),
            grain="transaction",
            primary_key=("transaction_id",),
            row_grain_label="transaction",
            expected_min_rows=100,
        ),
        DatasetSpec(
            id="budgets",
            label="Budget versus actual",
            filename="budgets.csv",
            description=(
                "Monthly budget against actual spend per department and category. "
                "One row per (month, department, category)."
            ),
            grain="month_department_category",
            primary_key=("period", "department", "category"),
            row_grain_label="month, department and category",
            expected_min_rows=100,
        ),
        DatasetSpec(
            id="vendors",
            label="Vendor register",
            filename="vendors.csv",
            description=(
                "Supplier register with FY2024 spend, contract type and term. "
                "One row per supplier relationship within a cost centre."
            ),
            grain="vendor",
            primary_key=("vendor_id",),
            row_grain_label="vendor",
            expected_min_rows=10,
        ),
    )
}


def dataset_ids() -> tuple[str, ...]:
    return tuple(DATASET_CATALOG)


def resolve_dataset(dataset_id: str) -> DatasetSpec | None:
    return DATASET_CATALOG.get(dataset_id)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """A single, addressable financial metric.

    ``formula`` is the canonical human-readable definition. It is surfaced in
    evidence items so an analyst can audit exactly how a number was produced.
    """

    id: str
    label: str
    unit: Unit
    source_dataset: str
    source_fields: tuple[str, ...]
    formula: str
    description: str
    supports_breakdown: tuple[Dimension, ...] = ()
    requires_comparison: bool = False
    alias_keywords: tuple[str, ...] = field(default=())


METRIC_CATALOG: Mapping[str, MetricSpec] = {
    spec.id: spec
    for spec in (
        MetricSpec(
            id="revenue",
            label="Revenue",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("revenue",),
            formula="revenue",
            description="Recognised revenue for the period.",
            supports_breakdown=(Dimension.QUARTER,),
            alias_keywords=("revenue", "sales", "top line", "turnover"),
        ),
        MetricSpec(
            id="cogs",
            label="Cost of goods sold",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("cogs",),
            formula="cogs",
            description="Direct cost of delivering the product or service.",
            supports_breakdown=(Dimension.QUARTER,),
            alias_keywords=("cogs", "cost of goods sold", "cost of sales", "cost of revenue"),
        ),
        MetricSpec(
            id="gross_profit",
            label="Gross profit",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("revenue", "cogs"),
            formula="gross_profit = revenue - cogs",
            description="Revenue less cost of goods sold.",
            supports_breakdown=(Dimension.QUARTER,),
            requires_comparison=True,
            alias_keywords=("gross profit", "gross margin dollars"),
        ),
        MetricSpec(
            id="gross_margin_pct",
            label="Gross margin",
            unit=Unit.PERCENT,
            source_dataset="financial_data",
            source_fields=("revenue", "cogs", "gross_profit"),
            formula="gross_margin_pct = gross_profit / revenue * 100",
            description="Gross profit as a percentage of revenue.",
            requires_comparison=True,
            alias_keywords=("gross margin", "gross margin percent", "gross margin %"),
        ),
        MetricSpec(
            id="operating_expenses",
            label="Operating expenses",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("operating_expenses",),
            formula=(
                "operating_expenses = cash_operating_expenses "
                "+ non_cash_operating_expenses"
            ),
            description=(
                "Total operating expense, split between cash spend and non-cash "
                "charges such as depreciation and share-based compensation."
            ),
            supports_breakdown=(Dimension.QUARTER,),
            requires_comparison=True,
            alias_keywords=(
                "operating expenses",
                "operating expense",
                "opex",
                "operating costs",
                "overheads",
            ),
        ),
        MetricSpec(
            id="cash_operating_expenses",
            label="Cash operating expenses",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("cash_operating_expenses",),
            formula="cash_operating_expenses",
            description="Operating expense settled in cash during the period.",
            requires_comparison=True,
            alias_keywords=("cash operating expenses", "cash opex"),
        ),
        MetricSpec(
            id="non_cash_operating_expenses",
            label="Non-cash operating expenses",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("non_cash_operating_expenses",),
            formula="non_cash_operating_expenses",
            description=(
                "Depreciation, amortisation and share-based compensation booked "
                "as operating expense."
            ),
            requires_comparison=True,
            alias_keywords=("non-cash expenses", "non cash opex", "depreciation"),
        ),
        MetricSpec(
            id="operating_income",
            label="Operating income",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("gross_profit", "operating_expenses"),
            formula="operating_income = gross_profit - operating_expenses",
            description="Gross profit less total operating expenses.",
            requires_comparison=True,
            alias_keywords=("operating income", "operating profit", "ebit", "operating result"),
        ),
        MetricSpec(
            id="operating_margin_pct",
            label="Operating margin",
            unit=Unit.PERCENT,
            source_dataset="financial_data",
            source_fields=("operating_income", "revenue"),
            formula="operating_margin_pct = operating_income / revenue * 100",
            description="Operating income as a percentage of revenue.",
            requires_comparison=True,
            alias_keywords=("operating margin", "operating margin percent", "ebit margin"),
        ),
        MetricSpec(
            id="cash_balance",
            label="Closing cash balance",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("cash_balance",),
            formula="cash_balance = cash_begin + operating + investing + financing",
            description="Cash and equivalents at the end of the period.",
            supports_breakdown=(Dimension.QUARTER,),
            alias_keywords=("cash", "cash balance", "closing cash"),
        ),
        MetricSpec(
            id="operating_cash_flow",
            label="Operating cash flow",
            unit=Unit.CURRENCY,
            source_dataset="financial_data",
            source_fields=("cash_operating_cash_flow",),
            formula=(
                "operating_cash_flow = operating_income + non_cash_operating_expenses "
                "- cash_tax - change_in_working_capital"
            ),
            description="Cash generated from operations in the period.",
            alias_keywords=("operating cash flow", "cash flow from operations", "ocf"),
        ),
        MetricSpec(
            id="total_expense",
            label="Total expense (ledger)",
            unit=Unit.CURRENCY,
            source_dataset="transactions",
            source_fields=("amount",),
            formula="total_expense = sum(expense amounts) - sum(credit amounts)",
            description=(
                "Net operating expense per the transaction ledger, grouped on "
                "demand by department, category or vendor."
            ),
            supports_breakdown=(
                Dimension.DEPARTMENT,
                Dimension.CATEGORY,
                Dimension.VENDOR,
                Dimension.MONTH,
                Dimension.QUARTER,
            ),
            requires_comparison=True,
            alias_keywords=("expenses", "spend", "total spend", "costs"),
        ),
        MetricSpec(
            id="transaction_count",
            label="Transaction count",
            unit=Unit.COUNT,
            source_dataset="transactions",
            source_fields=("transaction_id",),
            formula="transaction_count = count(transactions)",
            description="Number of ledger entries in scope.",
            supports_breakdown=(
                Dimension.DEPARTMENT,
                Dimension.CATEGORY,
                Dimension.VENDOR,
                Dimension.MONTH,
            ),
            alias_keywords=("transaction count", "number of transactions", "invoice count"),
        ),
        MetricSpec(
            id="avg_transaction_amount",
            label="Average transaction amount",
            unit=Unit.CURRENCY,
            source_dataset="transactions",
            source_fields=("amount",),
            formula="avg_transaction_amount = total_expense / transaction_count",
            description="Mean net spend per ledger entry.",
            alias_keywords=("average transaction", "average invoice"),
        ),
        MetricSpec(
            id="credit_amount",
            label="Credit memos",
            unit=Unit.CURRENCY,
            source_dataset="transactions",
            source_fields=("amount",),
            formula="credit_amount = sum(amount where transaction_type = credit)",
            description="Refunds and rebates that reduce net spend.",
            alias_keywords=("credits", "credit memos", "refunds"),
        ),
        MetricSpec(
            id="budget_amount",
            label="Budget",
            unit=Unit.CURRENCY,
            source_dataset="budgets",
            source_fields=("budget_amount",),
            formula="budget_amount = sum(budgets.budget_amount)",
            description="Approved budget for the period and scope.",
            supports_breakdown=(Dimension.DEPARTMENT, Dimension.CATEGORY, Dimension.MONTH),
            alias_keywords=("budget", "planned spend", "plan"),
        ),
        MetricSpec(
            id="budget_variance",
            label="Budget variance",
            unit=Unit.CURRENCY,
            source_dataset="budgets",
            source_fields=("budget_amount", "actual_amount"),
            formula="budget_variance = actual_amount - budget_amount",
            description="Positive values mean overspend; negative values mean underspend.",
            supports_breakdown=(Dimension.DEPARTMENT, Dimension.CATEGORY, Dimension.MONTH),
            alias_keywords=("variance", "budget variance", "overspend", "underspend"),
        ),
        MetricSpec(
            id="budget_utilisation_pct",
            label="Budget utilisation",
            unit=Unit.PERCENT,
            source_dataset="budgets",
            source_fields=("budget_amount", "actual_amount"),
            formula="budget_utilisation_pct = actual_amount / budget_amount * 100",
            description=(
                "Actual spend as a percentage of budget. 100% is on plan, above "
                "100% is overspend."
            ),
            supports_breakdown=(Dimension.DEPARTMENT, Dimension.CATEGORY, Dimension.MONTH),
            alias_keywords=("utilisation", "utilization", "budget used"),
        ),
        MetricSpec(
            id="vendor_count",
            label="Active vendors",
            unit=Unit.COUNT,
            source_dataset="vendors",
            source_fields=("vendor_id",),
            formula="vendor_count = count(distinct vendor_id)",
            description="Distinct suppliers in scope.",
            alias_keywords=("vendor count", "number of vendors", "suppliers"),
        ),
        MetricSpec(
            id="top_vendor_spend",
            label="Largest vendor spend",
            unit=Unit.CURRENCY,
            source_dataset="vendors",
            source_fields=("total_spend_2024",),
            formula="top_vendor_spend = max(vendors.total_spend_2024)",
            description="FY2024 spend booked against the single largest supplier.",
            alias_keywords=("top vendor", "largest vendor", "biggest supplier"),
        ),
        MetricSpec(
            id="vendor_concentration_pct",
            label="Top 5 vendor concentration",
            unit=Unit.PERCENT,
            source_dataset="vendors",
            source_fields=("total_spend_2024",),
            formula=(
                "vendor_concentration_pct = sum(top 5 total_spend_2024) "
                "/ sum(all total_spend_2024) * 100"
            ),
            description="Share of FY2024 spend concentrated in the five largest suppliers.",
            alias_keywords=("vendor concentration", "supplier concentration", "spend concentration"),
        ),
    )
}


def resolve_metric(metric_id: str) -> MetricSpec | None:
    return METRIC_CATALOG.get(metric_id)


def metrics_for_dataset(dataset_id: str) -> tuple[MetricSpec, ...]:
    return tuple(spec for spec in METRIC_CATALOG.values() if spec.source_dataset == dataset_id)


def match_metric_in_text(text: str) -> MetricSpec | None:
    """Find the best catalogued metric mentioned in free text.

    Matching is done on a fixed alias table - longest alias wins - so the
    result is deterministic and can never invent a metric name. Used by the
    deterministic question parser so a question such as "why did opex increase
    in Q3?" maps to a catalogued metric without any language model involved.
    """
    haystack = text.lower()
    best: MetricSpec | None = None
    best_length = 0
    for spec in METRIC_CATALOG.values():
        for alias in (spec.id, spec.label, *spec.alias_keywords):
            normalised = alias.strip().lower()
            if not normalised or normalised not in haystack:
                continue
            if len(normalised) > best_length:
                best, best_length = spec, len(normalised)
    return best


# ---------------------------------------------------------------------------
# Analysis types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisTypeSpec:
    """Capabilities and guard rails for one analysis type."""

    id: AnalysisType
    label: str
    description: str
    required_datasets: tuple[str, ...]
    supported_metrics: tuple[str, ...]
    allowed_dimensions: tuple[Dimension, ...]
    allowed_filters: tuple[str, ...]
    default_comparison: ComparisonMode
    default_granularity: Granularity
    requires_period: bool = True
    requires_comparison: bool = False
    max_breakdown_items: int = 10
    analyzer_path: str = ""

    def supports_metric(self, metric_id: str) -> bool:
        return metric_id in self.supported_metrics

    def supports_dimension(self, dimension: Dimension) -> bool:
        return dimension in self.allowed_dimensions

    def supports_filter(self, field_name: str) -> bool:
        return field_name in self.allowed_filters


ANALYSIS_TYPE_CATALOG: Mapping[AnalysisType, AnalysisTypeSpec] = {
    AnalysisType.METRIC_SNAPSHOT: AnalysisTypeSpec(
        id=AnalysisType.METRIC_SNAPSHOT,
        label="Metric snapshot",
        description="Report one metric for a period, optionally grouped by a dimension.",
        required_datasets=(),
        supported_metrics=tuple(METRIC_CATALOG),
        allowed_dimensions=(
            Dimension.DEPARTMENT,
            Dimension.CATEGORY,
            Dimension.VENDOR,
            Dimension.MONTH,
            Dimension.QUARTER,
        ),
        allowed_filters=("department", "category", "vendor_id"),
        default_comparison=ComparisonMode.NONE,
        default_granularity=Granularity.QUARTER,
        analyzer_path="app.analytics.snapshot:MetricSnapshotAnalyzer",
    ),
    AnalysisType.REVENUE_PERFORMANCE: AnalysisTypeSpec(
        id=AnalysisType.REVENUE_PERFORMANCE,
        label="Revenue performance",
        description=(
            "Revenue with cost of goods sold, gross profit and margin, compared "
            "against a prior period."
        ),
        required_datasets=("financial_data",),
        supported_metrics=("revenue", "cogs", "gross_profit", "gross_margin_pct"),
        allowed_dimensions=(Dimension.QUARTER,),
        allowed_filters=(),
        default_comparison=ComparisonMode.PRIOR_QUARTER,
        default_granularity=Granularity.QUARTER,
        requires_comparison=True,
        analyzer_path="app.analytics.revenue:RevenueAnalyzer",
    ),
    AnalysisType.EXPENSE_ANALYSIS: AnalysisTypeSpec(
        id=AnalysisType.EXPENSE_ANALYSIS,
        label="Expense analysis",
        description=(
            "Operating expense split into cash and non-cash, with the ledger "
            "broken down by department and category."
        ),
        required_datasets=("financial_data", "transactions"),
        supported_metrics=(
            "operating_expenses",
            "cash_operating_expenses",
            "non_cash_operating_expenses",
            "total_expense",
            "credit_amount",
            "transaction_count",
        ),
        allowed_dimensions=(Dimension.DEPARTMENT, Dimension.CATEGORY, Dimension.MONTH, Dimension.QUARTER),
        allowed_filters=("department", "category", "is_non_cash", "transaction_type"),
        default_comparison=ComparisonMode.PRIOR_QUARTER,
        default_granularity=Granularity.QUARTER,
        requires_comparison=True,
        analyzer_path="app.analytics.expense:ExpenseAnalyzer",
    ),
    AnalysisType.EXPENSE_VARIANCE: AnalysisTypeSpec(
        id=AnalysisType.EXPENSE_VARIANCE,
        label="Expense variance",
        description=(
            "Period-over-period movement in operating expense, attributed to the "
            "ledger categories that moved."
        ),
        required_datasets=("financial_data", "transactions"),
        supported_metrics=(
            "operating_expenses",
            "cash_operating_expenses",
            "non_cash_operating_expenses",
        ),
        allowed_dimensions=(Dimension.DEPARTMENT, Dimension.CATEGORY),
        allowed_filters=("department", "category"),
        default_comparison=ComparisonMode.PRIOR_QUARTER,
        default_granularity=Granularity.QUARTER,
        requires_comparison=True,
        analyzer_path="app.analytics.expense:ExpenseVarianceAnalyzer",
    ),
    AnalysisType.PROFITABILITY: AnalysisTypeSpec(
        id=AnalysisType.PROFITABILITY,
        label="Profitability",
        description=(
            "Full income statement walk from revenue to operating income with "
            "margin analysis against a prior period."
        ),
        required_datasets=("financial_data",),
        supported_metrics=(
            "revenue",
            "cogs",
            "gross_profit",
            "gross_margin_pct",
            "operating_expenses",
            "operating_income",
            "operating_margin_pct",
        ),
        allowed_dimensions=(Dimension.QUARTER,),
        allowed_filters=(),
        default_comparison=ComparisonMode.PRIOR_QUARTER,
        default_granularity=Granularity.QUARTER,
        requires_comparison=True,
        analyzer_path="app.analytics.profitability:ProfitabilityAnalyzer",
    ),
    AnalysisType.BUDGET_VARIANCE: AnalysisTypeSpec(
        id=AnalysisType.BUDGET_VARIANCE,
        label="Budget variance",
        description=(
            "Actual spend against approved budget, with the largest overspends "
            "identified."
        ),
        required_datasets=("budgets", "transactions"),
        supported_metrics=(
            "budget_amount",
            "budget_variance",
            "budget_utilisation_pct",
            "total_expense",
        ),
        allowed_dimensions=(Dimension.DEPARTMENT, Dimension.CATEGORY, Dimension.MONTH),
        allowed_filters=("department", "category"),
        default_comparison=ComparisonMode.NONE,
        default_granularity=Granularity.MONTH,
        analyzer_path="app.analytics.budget_variance:BudgetVarianceAnalyzer",
    ),
    AnalysisType.VENDOR_SPEND: AnalysisTypeSpec(
        id=AnalysisType.VENDOR_SPEND,
        label="Vendor spend",
        description="Spend by supplier, with concentration and contract metadata.",
        required_datasets=("vendors", "transactions"),
        supported_metrics=(
            "total_expense",
            "vendor_count",
            "top_vendor_spend",
            "vendor_concentration_pct",
            "transaction_count",
            "avg_transaction_amount",
        ),
        allowed_dimensions=(Dimension.VENDOR, Dimension.DEPARTMENT, Dimension.CATEGORY),
        allowed_filters=("department", "category", "contract_type"),
        default_comparison=ComparisonMode.PRIOR_YEAR,
        default_granularity=Granularity.VENDOR,
        analyzer_path="app.analytics.vendor_spend:VendorSpendAnalyzer",
    ),
    AnalysisType.TREND: AnalysisTypeSpec(
        id=AnalysisType.TREND,
        label="Trend",
        description=(
            "Ordered series for a metric across periods with growth rate and "
            "direction."
        ),
        required_datasets=(),
        supported_metrics=tuple(METRIC_CATALOG),
        allowed_dimensions=(Dimension.MONTH, Dimension.QUARTER),
        allowed_filters=("department", "category"),
        default_comparison=ComparisonMode.NONE,
        default_granularity=Granularity.QUARTER,
        max_breakdown_items=24,
        analyzer_path="app.analytics.trend:TrendAnalyzer",
    ),
}


def resolve_analysis_type(analysis_type: AnalysisType | str) -> AnalysisTypeSpec | None:
    try:
        return ANALYSIS_TYPE_CATALOG[AnalysisType(analysis_type)]
    except ValueError:
        return None