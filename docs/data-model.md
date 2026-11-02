# FinSight Data Model

All data is synthetic. No real company financial information is used.

---

## Datasets

### `financial_data.csv` — Quarterly Income Statement

**Grain:** one row per fiscal quarter.

| Column | Type | Description |
|---|---|---|
| `period` | string | Fiscal quarter key, e.g. `2024-Q3` |
| `fiscal_year` | int | Calendar year |
| `quarter` | int 1–4 | Quarter within the year |
| `period_start` | date | First day of the quarter |
| `period_end` | date | Last day of the quarter |
| `currency` | string | Always `USD` |
| `revenue` | float | Recognised revenue |
| `cogs` | float | Cost of goods sold |
| `gross_profit` | float | `revenue − cogs` (recomputed, not read from file) |
| `operating_expenses` | float | `cash_operating_expenses + non_cash_operating_expenses` |
| `operating_income` | float | `gross_profit − operating_expenses` |
| `cash_operating_expenses` | float | Cash portion of opex |
| `non_cash_operating_expenses` | float | Depreciation, amortisation, stock-based comp |
| `cash_begin` | float | Opening cash balance |
| `cash_operating_cash_flow` | float | Net cash from operations |
| `cash_investing_cash_flow` | float | Capex and investments |
| `cash_financing_cash_flow` | float | Debt and equity movements |
| `cash_balance` | float | `cash_begin + operating + investing + financing` |

**Coverage:** FY2023-Q1 through FY2024-Q4 (8 rows).

---

### `transactions.csv` — Operating Expense Ledger

**Grain:** one row per expense or credit memo.

| Column | Type | Description |
|---|---|---|
| `transaction_id` | string | Unique identifier, e.g. `TXN-2024-0001` |
| `date` | date | Transaction date |
| `period` | string | Month key, e.g. `2024-07` |
| `quarter` | string | Fiscal quarter key, e.g. `2024-Q3` |
| `department` | string | Cost centre |
| `category` | string | Expense category |
| `vendor_id` | string \| null | Foreign key to `vendors.csv`; null for non-cash rows |
| `vendor` | string \| null | Vendor name (denormalised for readability) |
| `amount` | float > 0 | **Always positive.** Sign comes from `transaction_type`. |
| `transaction_type` | enum | `expense` (adds to spend) or `credit` (subtracts) |
| `is_non_cash` | bool | True for depreciation, amortisation, stock-based comp |
| `description` | string | Human-readable description |

**Coverage:** FY2024 only (233 rows).  
**Sign convention:** `net_spend = Σ expense − Σ credit` (computed in Python, never stored as signed amounts).

---

### `budgets.csv` — Monthly Budget vs Actual

**Grain:** one row per month × department × category.

| Column | Type | Description |
|---|---|---|
| `period` | string | Month key, e.g. `2024-07` |
| `quarter` | string | Fiscal quarter key |
| `department` | string | Cost centre |
| `category` | string | Expense category |
| `budget_amount` | float ≥ 0 | Approved budget |
| `actual_amount` | float | Realised spend |
| `variance_amount` | float | `actual − budget` (positive = overspend) |
| `variance_pct` | float \| null | `(actual − budget) / budget × 100` |
| `utilisation_pct` | float \| null | `actual / budget × 100` |

**Coverage:** FY2024 (148 rows).  
**Integrity check:** `variance_amount` and `utilisation_pct` are recomputed at load time and checked against the file values.

---

### `vendors.csv` — Vendor Master

**Grain:** one row per vendor.

| Column | Type | Description |
|---|---|---|
| `vendor_id` | string | Unique identifier, e.g. `V-1001` |
| `vendor_name` | string | Supplier name |
| `category` | string | Primary expense category |
| `department` | string | Primary cost centre |
| `monthly_spend` | float | `total_spend_2024 / 12` |
| `total_spend_2024` | float | Ledger total for FY2024 |
| `transaction_count_2024` | int | Number of transactions in FY2024 |
| `avg_transaction_amount` | float | `total_spend_2024 / transaction_count_2024` |
| `contract_type` | string | `retainer`, `project`, `usage`, `subscription`, `perpetual` |
| `contract_start` | date | Contract start date |
| `contract_end` | date | Contract expiry |
| `status` | string | `active` or `inactive` |

**Coverage:** 17 vendors.  
**Integrity check:** `total_spend_2024` is reconciled against the ledger sum by `vendor_id`.

---

## Relationships

```
financial_data  ──(quarterly cash opex)──►  transactions
                                                │
transactions  ──(vendor_id FK)──►  vendors
                │
transactions  ──(period + category)──►  budgets
```

The transaction ledger for FY2024 reconciles to the `cash_operating_expenses` column of `financial_data` for all four 2024 quarters. Budgets reconcile to the ledger at the month × category grain.

---

## Typed Schemas (Pydantic)

| Schema | File | Maps to |
|---|---|---|
| `FinancialPeriod` | `schemas/dataset.py` | `financial_data.csv` rows |
| `Transaction` | `schemas/dataset.py` | `transactions.csv` rows |
| `Budget` | `schemas/dataset.py` | `budgets.csv` rows |
| `Vendor` | `schemas/dataset.py` | `vendors.csv` rows |
| `FinancialMetric` | `schemas/analysis.py` | Computed metric with provenance |
| `AnalysisPlan` | `schemas/analysis.py` | Validated analysis request |
| `EvidenceItem` | `schemas/evidence.py` | One auditable financial fact |
| `EvidencePackage` | `schemas/evidence.py` | Complete bounded fact set for one answer |
| `Answer` | `schemas/question.py` | Structured response to `POST /questions` |

All schemas use `model_config = ConfigDict(extra="forbid")`. Unknown fields are rejected at validation time.

---

## Generator

`scripts/generate_data.py` produces all four files from a single seed (`SEED = 20260101`). Running it again always produces the same output.

Key assumptions embedded in the generator:

| Assumption | Value |
|---|---|
| Opening cash balance | 6,200,000.00 |
| Effective tax rate | 22% |
| Capex as % of revenue | 2.5% |
| Working capital change as % of revenue change | 18% |