"""Analyser wiring.

Kept in its own module on purpose: :mod:`app.analytics` re-exports nothing, so
this file is the single place that knows every concrete analyser. Nothing in
the analytics core imports a concrete analyser, which keeps the import graph
acyclic.
"""

from __future__ import annotations

from app.analytics.base import AnalyzerRegistry
from app.analytics.budget_variance import BudgetVarianceAnalyzer
from app.analytics.expense import ExpenseAnalyzer, ExpenseVarianceAnalyzer
from app.analytics.profitability import ProfitabilityAnalyzer
from app.analytics.revenue import RevenueAnalyzer
from app.analytics.snapshot import MetricSnapshotAnalyzer
from app.analytics.trend import TrendAnalyzer
from app.analytics.vendor_spend import VendorSpendAnalyzer


def build_registry() -> AnalyzerRegistry:
    """Register one analyser per catalogued analysis type.

    Raises if the catalog and the implementations disagree, so a new analysis
    type cannot be published without code behind it.
    """
    registry = AnalyzerRegistry()
    for analyzer in (
        MetricSnapshotAnalyzer(),
        RevenueAnalyzer(),
        ExpenseAnalyzer(),
        ExpenseVarianceAnalyzer(),
        ProfitabilityAnalyzer(),
        BudgetVarianceAnalyzer(),
        VendorSpendAnalyzer(),
        TrendAnalyzer(),
    ):
        registry.register(analyzer)
    registry.validate_catalog_coverage()
    return registry