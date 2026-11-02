# FinSight Analytics

All financial calculations in FinSight are deterministic Python/Pandas. A language model never performs arithmetic; it only interprets questions and explains pre-computed results.

---

## Principles

1. **Results are reproducible.** Same plan + same data = same numbers. No randomness.
2. **Zero denominators are explicit.** `safe_percentage` and `safe_percentage_change` return `None` rather than `NaN`, infinity, or a silent zero.
3. **Every output carries its formula.** Every `FinancialMetric` and `EvidenceItem` includes a `calculation` string so the number can be audited without trusting the system.
4. **No LLM in the calculation path.** Analysers receive a `DatasetRepository` and a `AnalysisPlan`. They return `AnalyzerOutput`. They cannot make network calls.

---

## Arithmetic Primitives (`analytics/base.py`)

```python
safe_percentage(numerator, denominator)
# Returns numerator / denominator * 100, or None when denominator == 0 or NaN.

safe_percentage_change(current, previous)
# Returns (current - previous) / abs(previous) * 100, or None when previous == 0 or NaN.

absolute_change(current, previous)
# Returns current - previous, or None when either input is NaN.

direction_of(current, previous, tolerance=0.01)
# Returns INCREASE / DECREASE / FLAT / UNKNOWN.
# Changes within the tolerance band are classified FLAT.

safe_average(total, count)
# Returns total / count, or None when count == 0 or NaN.

optional_float(value)
# Coerces a Pandas cell to float, returning None for NaN/NA/unparseable inputs.
```

All primitives are tested in `test_numeric_helpers.py`.

---

## Sign Convention

`amount` in `transactions.csv` is always positive. The analytical sign comes from `transaction_type`:

```
net_spend = Σ expense_amounts − Σ credit_amounts
```

This is computed by `net_cash_spend(transactions)` in `data/integrity.py`. Analysers never apply sign logic themselves; they call this helper.

---

## Income Statement

```
gross_profit         = revenue − cogs
operating_income     = gross_profit − operating_expenses
operating_expenses   = cash_operating_expenses + non_cash_operating_expenses
gross_margin_pct     = gross_profit / revenue × 100
operating_margin_pct = operating_income / revenue × 100
```

All three derived columns (`gross_profit`, `operating_income`, `operating_expenses`) are recomputed in the analysers from the source columns. The values in the CSV file are checked against the recomputed values by the `check_income_statement_arithmetic` integrity check at startup.

---

## Cash Flow

```
cash_balance = cash_begin + cash_operating_cash_flow
             + cash_investing_cash_flow
             + cash_financing_cash_flow

cash_begin[t] = cash_balance[t−1]
```

Validated by `check_cash_roll_forward` and `check_cash_continuity`.

---

## Budget Variance

```
budget_variance      = actual_amount − budget_amount
                       (positive = overspend, negative = underspend)

budget_utilisation   = actual_amount / budget_amount × 100

contribution_pct     = row_variance / total_variance × 100
```

Validated by `check_budget_derived_columns`.

---

## Vendor Spend

```
net_vendor_spend     = Σ expense − Σ credit  (grouped by vendor_id)

vendor_concentration = top_5_vendor_net_spend / total_net_spend × 100
```

Validated by `check_vendor_rollup`.

---

## Supported Analysis Types

### `metric_snapshot`
Returns a single metric for a period. No arithmetic beyond reading and formatting.

### `revenue_performance`
```
gross_profit   = revenue − cogs          (recomputed from source columns)
gross_margin   = gross_profit / revenue × 100
```
When a comparison period is present, `change` and `percentage_change` are computed for each metric.

### `expense_analysis`
Reads `cash_operating_expenses` and `non_cash_operating_expenses` from the income statement, then attributes spend from the transaction ledger by the requested dimension (department, category, vendor, month).

### `expense_variance`
Period-over-period movement at the category level. Each row carries:
```
change                   = current_category_spend − prior_category_spend
contribution_to_change   = change / total_operating_expense_change × 100
```

### `profitability`
Full P&L walk: revenue → COGS → gross profit → operating expenses → operating income, with margins.

### `budget_variance`
Actual vs approved, by dimension. Overspend and underspend rows are identified separately. Utilisation is computed from actuals and budget at the aggregated scope level.

### `vendor_spend`
Ranked net spend by vendor. Top-5 concentration, average transaction amount.

### `trend`
Ordered time series. Each point carries:
```
comparison_value = previous_point.value
change           = value − comparison_value
percentage_change = change / |comparison_value| × 100
```
The headline metric compares the first and last points across the full series.

---

## Calculation Correctness

`test_analytics.py` recomputes every reference value in plain Python (not via the analyser) and checks agreement. If the analyser disagrees with the reference, the test fails. This means analytical errors are caught at the unit level, not discovered in production.

The benchmark suite (`test_benchmark.py`) checks specific numerical targets for 15 financial questions and verifies that cited evidence IDs exist in the returned evidence package.

---

## Filters

Analysers accept equality filters (`field in [values]`) applied as Pandas `.isin()` masks. Filter fields must be in each analysis type's `allowed_filters` set; attempting an unlisted field raises `PlanValidationError`. There is no SQL and no dynamic column access.

---

## Period Resolution

Periods are fiscal quarter keys (`YYYY-Qn`). Months are `YYYY-MM`. The repository exposes two vocabulary properties:

- `repository.periods` — sorted distinct quarters from `financial_data.csv`
- `repository.months` — sorted distinct months from `transactions.csv` (deduplicated)

`resolve_month_scope(plan, repository)` converts a quarter range to a list of month keys for ledger filtering.