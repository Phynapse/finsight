"""Vendor spend and concentration analysis."""

from __future__ import annotations

from app.analytics.base import (
    financial_metric,
    LEDGER_DIMENSION_COLUMN,
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    apply_filters,
    ledger_for_period,
    make_dimension_value,
    resolve_month_scope,
    safe_average,
    safe_percentage,
)
from app.core.errors import NoDataForPlanError
from app.models.catalog import resolve_metric
from app.models.enums import AnalysisType, Dimension


class VendorSpendAnalyzer(Analyzer):
    """Spend by supplier, with concentration and contract context.

    The vendor register supplies the contract metadata; the ledger supplies the
    spend. The register is the declared FY2024 roll-up of the ledger, and that
    roll-up is asserted at startup, so the two cannot disagree.
    """

    analysis_type = AnalysisType.VENDOR_SPEND

    def run(self, context: AnalysisContext) -> AnalyzerOutput:
        plan = context.plan
        months = resolve_month_scope(plan, context.repository)

        transactions = apply_filters(
            context.transactions_frame(), plan, context, context.spec.allowed_filters
        )
        vendors = apply_filters(
            context.vendors_frame(), plan, context, ("department", "category", "contract_type")
        )

        scoped = ledger_for_period(transactions, months)
        scoped = scoped[scoped["vendor_id"].notna()]
        if scoped.empty:
            raise NoDataForPlanError(
                "No vendor transactions match this plan.",
                details={"months": months, "filters": [item.field for item in plan.filters]},
            )

        registered = set(vendors["vendor_id"].tolist())
        grouped = (
            scoped.groupby("vendor_id", as_index=False)
            .agg(
                net_amount=("net_amount", "sum"),
                line_count=("net_amount", "size"),
                vendor=("vendor", "first"),
            )
            .sort_values(by=["net_amount", "vendor_id"], ascending=[False, True], kind="stable")
            .reset_index(drop=True)
        )
        unknown = sorted(set(grouped["vendor_id"].tolist()) - set(context.vendors_frame()["vendor_id"].tolist()))
        if unknown:
            context.warn(f"{len(unknown)} vendor id(s) in the ledger are absent from the register.")

        total = round(float(grouped["net_amount"].sum()), 2)
        vendor_count = int(grouped["vendor_id"].nunique())
        top_spend = round(float(grouped["net_amount"].max()), 2)
        top_five = round(float(grouped["net_amount"].head(5).sum()), 2)
        concentration = safe_percentage(top_five, total)

        metrics = [
            financial_metric(resolve_metric("vendor_count"), vendor_count, context=context, period=plan.period),
            financial_metric(resolve_metric("top_vendor_spend"), top_spend, context=context, period=plan.period),
        ]
        if concentration is not None:
            metrics.append(
                financial_metric(
                    resolve_metric("vendor_concentration_pct"),
                    concentration,
                    context=context,
                    period=plan.period,
                    inputs={"top_5_spend": top_five, "total_spend": total},
                )
            )
        average = safe_average(total, vendor_count)
        if average is not None:
            metrics.append(
                financial_metric(
                    resolve_metric("avg_transaction_amount"),
                    average,
                    context=context,
                    period=plan.period,
                    inputs={"total_expense": total, "vendor_count": vendor_count},
                )
            )

        dimension = plan.dimensions[0] if plan.dimensions else Dimension.VENDOR
        if dimension is Dimension.VENDOR:
            # The same legal supplier can hold several vendor ids, one per cost
            # centre, so the label carries the owning department to stay unique.
            owners = (
                context.vendors_frame().set_index("vendor_id")["department"].to_dict()
            )
            rows = [
                make_dimension_value(
                    Dimension.VENDOR,
                    str(record["vendor_id"]),
                    float(record["net_amount"]),
                    label=f"{record['vendor']} ({owners.get(record['vendor_id'], 'unknown')})",
                    total=total,
                    transaction_count=int(record["line_count"]),
                )
                for record in grouped.to_dict(orient="records")
            ]
            methodology = [
                "net spend per vendor = sum(expense) - sum(credit) over the scoped months",
                "vendors ranked by absolute net spend",
                f"top 5 vendors account for {concentration:.2f}% of spend" if concentration else "top 5 concentration unavailable",
            ]
        else:
            column = LEDGER_DIMENSION_COLUMN[dimension]
            sub = (
                scoped.groupby(column, as_index=False)
                .agg(net_amount=("net_amount", "sum"), line_count=("net_amount", "size"))
                .sort_values(by=["net_amount", column], ascending=[False, True], kind="stable")
                .reset_index(drop=True)
            )
            rows = [
                make_dimension_value(
                    dimension,
                    str(getattr(record, column)),
                    float(record.net_amount),
                    total=total,
                    transaction_count=int(record.line_count),
                )
                for record in sub.itertuples(index=False)
            ]
            methodology = [f"net spend grouped by {dimension.value}"]

        if registered and concentration is not None and concentration >= 40.0:
            context.warn(
                f"Spend is concentrated: the top 5 vendors are {concentration:.2f}% of "
                "period spend."
            )

        return AnalyzerOutput(
            metrics=metrics,
            breakdown=rows[: plan.limit],
            methodology=methodology,
            period=plan.period,
            comparison_period=plan.comparison_period,
            row_count=len(rows),
        )
