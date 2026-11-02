"""Cross-dataset integrity checks.

These assertions run once at startup. They are what makes the synthetic dataset
trustworthy: every number in the UI can be traced back to a ledger, and the
ledger ties back to the income statement.
"""

from __future__ import annotations

import pandas as pd

from app.schemas.dataset_api import IntegrityCheck

TOLERANCE = 0.01


def _money(value: float) -> str:
    return f"{value:,.2f}"


def net_cash_spend(transactions: pd.DataFrame) -> pd.Series:
    """Net cash spend: expenses add, credit memos subtract."""
    signed = pd.Series(
        [
            value if transaction_type == "expense" else -value
            for value, transaction_type in zip(
                transactions["amount"].tolist(),
                transactions["transaction_type"].tolist(),
                strict=True,
            )
        ],
        index=transactions.index,
        dtype="float64",
    )
    return signed


def _cash_rows(transactions: pd.DataFrame) -> pd.DataFrame:
    return transactions[transactions["is_non_cash"] == False]  # noqa: E712 - explicit boolean mask


def check_income_statement_arithmetic(financial: pd.DataFrame) -> IntegrityCheck:
    """gross_profit = revenue - cogs and operating_income = gross_profit - opex."""
    gross = financial["revenue"] - financial["cogs"]
    operating = gross - financial["operating_expenses"]
    gross_error = float((gross - financial["gross_profit"]).abs().max())
    operating_error = float((operating - financial["operating_income"]).abs().max())
    return IntegrityCheck(
        id="income_statement_arithmetic",
        description=(
            "gross_profit = revenue - cogs; operating_income = gross_profit - operating_expenses"
        ),
        datasets=["financial_data"],
        passed=gross_error <= TOLERANCE and operating_error <= TOLERANCE,
        observed=f"max gross error {gross_error:.2f}, max operating error {operating_error:.2f}",
        expected="both within 0.01",
    )


def check_opex_cash_split(financial: pd.DataFrame) -> IntegrityCheck:
    """operating_expenses = cash + non-cash."""
    recomputed = financial["cash_operating_expenses"] + financial["non_cash_operating_expenses"]
    delta = float((recomputed - financial["operating_expenses"]).abs().max())
    return IntegrityCheck(
        id="operating_expense_cash_split",
        description=(
            "operating_expenses = cash_operating_expenses + non_cash_operating_expenses"
        ),
        datasets=["financial_data"],
        passed=delta <= TOLERANCE,
        observed=f"max delta {delta:.2f}",
        expected="within 0.01",
    )


def check_cash_roll_forward(financial: pd.DataFrame) -> IntegrityCheck:
    """cash_balance = cash_begin + operating + investing + financing."""
    ordered = financial.sort_values("period").reset_index(drop=True)
    recomputed = (
        ordered["cash_begin"]
        + ordered["cash_operating_cash_flow"]
        + ordered["cash_investing_cash_flow"]
        + ordered["cash_financing_cash_flow"]
    )
    delta = float((recomputed - ordered["cash_balance"]).abs().max())
    return IntegrityCheck(
        id="cash_roll_forward",
        description="cash_balance = cash_begin + operating + investing + financing",
        datasets=["financial_data"],
        passed=delta <= TOLERANCE,
        observed=f"max delta {delta:.2f}",
        expected="within 0.01",
    )


def check_cash_continuity(financial: pd.DataFrame) -> IntegrityCheck:
    """cash_begin(t) = cash_balance(t - 1)."""
    ordered = financial.sort_values("period").reset_index(drop=True)
    previous_closes = ordered["cash_balance"].to_numpy().tolist()[:-1]
    period_opens = ordered["cash_begin"].to_numpy().tolist()[1:]
    delta = max((abs(a - b) for a, b in zip(period_opens, previous_closes, strict=True)), default=0.0)
    return IntegrityCheck(
        id="cash_continuity",
        description="cash_begin of a period equals cash_balance of the preceding period",
        datasets=["financial_data"],
        passed=delta <= TOLERANCE,
        observed=f"max delta {delta:.2f}",
        expected="within 0.01",
    )


def check_transactions_tie_to_income_statement(
    financial: pd.DataFrame, transactions: pd.DataFrame
) -> IntegrityCheck:
    """FY2024 cash ledger equals cash_operating_expenses, quarter by quarter."""
    cash_rows = _cash_rows(transactions).assign(signed=net_cash_spend(_cash_rows(transactions)))
    ledger = cash_rows.groupby("quarter", as_index=True)["signed"].sum().round(2)
    statements = (
        financial[financial["fiscal_year"] == 2024]
        .set_index("period")["cash_operating_expenses"]
        .round(2)
    )
    mismatches: list[str] = []
    for period, expected in statements.items():
        observed = float(ledger.get(period, float("nan")))
        if abs(observed - float(expected)) > TOLERANCE:
            mismatches.append(
                f"{period}: ledger {_money(observed)} vs statement {_money(float(expected))}"
            )
    return IntegrityCheck(
        id="transactions_tie_to_income_statement",
        description="FY2024 cash ledger net spend equals cash_operating_expenses per quarter",
        datasets=["financial_data", "transactions"],
        passed=not mismatches,
        observed=(
            "; ".join(mismatches)
            if mismatches
            else f"{len(statements)} quarters reconciled"
        ),
        expected="all quarters within 0.01",
    )


def check_budgets_tie_to_transactions(
    transactions: pd.DataFrame, budgets: pd.DataFrame
) -> IntegrityCheck:
    """budgets.actual_amount equals the ledger for the same month and category.

    Budgets cover *total* operating expense, so both cash and non-cash ledger
    rows are included here (cash-only reconciliation is a separate assertion).
    """
    signed = transactions.assign(signed=net_cash_spend(transactions))
    ledger = (
        signed.groupby(["period", "department", "category"], as_index=True)["signed"]
        .sum()
        .round(2)
    )
    mismatches: list[str] = []
    for row in budgets.itertuples(index=False):
        observed = float(ledger.get((row.period, row.department, row.category), 0.0))
        if abs(observed - float(row.actual_amount)) > TOLERANCE:
            mismatches.append(
                f"{row.period}/{row.department}/{row.category}: "
                f"{_money(observed)} vs {_money(float(row.actual_amount))}"
            )
    return IntegrityCheck(
        id="budgets_tie_to_transactions",
        description=(
            "budgets.actual_amount equals net ledger spend (cash and non-cash) per "
            "month, department and category"
        ),
        datasets=["transactions", "budgets"],
        passed=not mismatches,
        observed=(
            "; ".join(mismatches[:5])
            if mismatches
            else f"{len(budgets)} budget lines reconciled"
        ),
        expected="all lines within 0.01",
    )


def check_budget_derived_columns(budgets: pd.DataFrame) -> IntegrityCheck:
    """The variance and utilisation columns agree with budget and actual."""
    variance = budgets["actual_amount"] - budgets["budget_amount"]
    variance_ok = bool((variance - budgets["variance_amount"]).abs().max() <= TOLERANCE)
    safe_budget = budgets["budget_amount"].where(budgets["budget_amount"] != 0)
    utilisation = (budgets["actual_amount"] / safe_budget * 100).astype("Float64")
    observed_utilisation = pd.to_numeric(budgets["utilisation_pct"], errors="coerce").astype("Float64")
    both = utilisation.where(utilisation.notna(), observed_utilisation)
    utilisation_ok = bool((both - observed_utilisation).abs().max() <= 0.01)
    return IntegrityCheck(
        id="budget_derived_columns",
        description="variance_amount = actual - budget; utilisation_pct = actual / budget * 100",
        datasets=["budgets"],
        passed=variance_ok and utilisation_ok,
        observed=f"variance_ok={variance_ok}, utilisation_ok={utilisation_ok}",
        expected="both true",
    )


def check_vendor_rollup(transactions: pd.DataFrame, vendors: pd.DataFrame) -> IntegrityCheck:
    """Vendor totals equal the ledger, and monthly_spend is the annual total / 12."""
    cash_rows = transactions[transactions["vendor_id"].notna()].copy()
    cash_rows["signed"] = net_cash_spend(cash_rows)
    ledger = cash_rows.groupby("vendor_id", as_index=True)["signed"].sum().round(2)
    mismatches: list[str] = []
    for row in vendors.itertuples(index=False):
        observed = float(ledger.get(row.vendor_id, 0.0))
        if abs(observed - float(row.total_spend_2024)) > TOLERANCE:
            mismatches.append(
                f"{row.vendor_id}: {_money(observed)} vs {_money(float(row.total_spend_2024))}"
            )
    monthly_mismatches = [
        row.vendor_id
        for row in vendors.itertuples(index=False)
        if round(float(row.total_spend_2024) / 12, 2) != float(row.monthly_spend)
    ]
    return IntegrityCheck(
        id="vendor_rollup",
        description=(
            "vendors.total_spend_2024 equals the ledger and monthly_spend = total / 12"
        ),
        datasets=["transactions", "vendors"],
        passed=not mismatches and not monthly_mismatches,
        observed=f"{len(mismatches)} total mismatches, {len(monthly_mismatches)} monthly mismatches",
        expected="no mismatches",
    )


def check_vendor_foreign_keys(transactions: pd.DataFrame, vendors: pd.DataFrame) -> IntegrityCheck:
    """Every cash transaction references a registered vendor."""
    known = set(vendors["vendor_id"].tolist())
    cash_rows = _cash_rows(transactions)
    unknown = sorted({str(value) for value in cash_rows["vendor_id"].tolist() if value not in known})
    non_cash = transactions[transactions["is_non_cash"] == True]  # noqa: E712 - explicit boolean mask
    leaked = int(non_cash["vendor_id"].notna().sum())
    return IntegrityCheck(
        id="vendor_foreign_keys",
        description="cash transactions carry a registered vendor_id; non-cash rows carry none",
        datasets=["transactions", "vendors"],
        passed=not unknown and leaked == 0,
        observed=(
            f"{len(unknown)} unknown vendor ids, {leaked} non-cash rows with a vendor"
            if unknown or leaked
            else f"{len(cash_rows)} cash rows, {len(non_cash)} non-cash rows verified"
        ),
        expected="no dangling references",
    )


def check_period_alignment(
    financial: pd.DataFrame, transactions: pd.DataFrame, budgets: pd.DataFrame
) -> IntegrityCheck:
    """Every transaction and budget period maps onto a known fiscal quarter."""
    known_quarters = set(financial["period"].tolist())
    known_months = {
        f"{period[:4]}-{month:02d}" for period in known_quarters for month in range(1, 13)
    }
    bad_transactions = sorted(set(transactions["quarter"].tolist()) - known_quarters)
    bad_budgets = sorted(set(budgets["period"].tolist()) - known_months)
    return IntegrityCheck(
        id="period_alignment",
        description="transaction quarters and budget months map onto known fiscal periods",
        datasets=["financial_data", "transactions", "budgets"],
        passed=not bad_transactions and not bad_budgets,
        observed=(
            f"unknown quarters {bad_transactions}, unknown months {bad_budgets}"
            if bad_transactions or bad_budgets
            else f"{len(known_quarters)} fiscal quarters covered"
        ),
        expected="all periods known",
    )


def check_unique_keys(
    financial: pd.DataFrame,
    transactions: pd.DataFrame,
    budgets: pd.DataFrame,
    vendors: pd.DataFrame,
) -> IntegrityCheck:
    """Primary keys are unique in every dataset."""
    issues: list[str] = []
    if financial["period"].duplicated().any():
        issues.append("financial_data.period")
    if transactions["transaction_id"].duplicated().any():
        issues.append("transactions.transaction_id")
    if budgets[["period", "department", "category"]].duplicated().any():
        issues.append("budgets(period, department, category)")
    if vendors["vendor_id"].duplicated().any():
        issues.append("vendors.vendor_id")
    return IntegrityCheck(
        id="unique_primary_keys",
        description="primary keys are unique in every dataset",
        datasets=["financial_data", "transactions", "budgets", "vendors"],
        passed=not issues,
        observed=", ".join(issues) if issues else "all keys unique",
        expected="no duplicates",
    )