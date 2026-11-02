"""Pydantic contracts for the four bundled datasets.

Each CSV row is validated into a strictly typed model at load time, so an
analyser can never operate on an unvalidated dictionary.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Currency, TransactionType

_STRICT = ConfigDict(extra="forbid", frozen=True)


class _StrictModel(BaseModel):
    model_config = _STRICT


class FinancialPeriod(_StrictModel):
    """One fiscal quarter of the income statement and cash roll-forward."""

    period: str = Field(description="Fiscal period key, for example '2024-Q3'.")
    fiscal_year: int = Field(ge=1900, le=2200)
    quarter: int = Field(ge=1, le=4)
    period_start: date
    period_end: date
    currency: Currency = Currency.USD
    revenue: float
    cogs: float
    gross_profit: float
    operating_expenses: float
    operating_income: float
    cash_operating_expenses: float
    non_cash_operating_expenses: float
    cash_begin: float
    cash_operating_cash_flow: float
    cash_investing_cash_flow: float
    cash_financing_cash_flow: float
    cash_balance: float

    @property
    def period_label(self) -> str:
        return f"Q{self.quarter} {self.fiscal_year}"


class Transaction(_StrictModel):
    """A single operating expense or credit memo."""

    transaction_id: str = Field(min_length=1, max_length=64)
    date: date
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Month key, for example '2024-07'.")
    quarter: str = Field(pattern=r"^\d{4}-Q[1-4]$", description="Fiscal quarter key, '2024-Q3'.")
    department: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    vendor_id: str | None = Field(default=None, max_length=64)
    vendor: str | None = Field(default=None, max_length=120)
    amount: float = Field(gt=0, description="Positive magnitude; type carries the direction.")
    transaction_type: TransactionType
    is_non_cash: bool
    description: str = Field(min_length=1, max_length=200)

    @field_validator("vendor", "vendor_id", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class Budget(_StrictModel):
    """Budget against actual for one month, department and category."""

    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    quarter: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    department: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    budget_amount: float = Field(ge=0)
    actual_amount: float
    variance_amount: float
    variance_pct: float | None = None
    utilisation_pct: float | None = None


class Vendor(_StrictModel):
    """A supplier relationship within one cost centre."""

    vendor_id: str = Field(min_length=1, max_length=64)
    vendor_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=1, max_length=80)
    monthly_spend: float = Field(ge=0)
    total_spend_2024: float = Field(ge=0)
    transaction_count_2024: int = Field(ge=0)
    avg_transaction_amount: float = Field(ge=0)
    contract_type: str = Field(min_length=1, max_length=40)
    contract_start: date
    contract_end: date
    status: str = Field(min_length=1, max_length=20)


DATASET_ROW_MODELS: dict[str, type[_StrictModel]] = {
    "financial_data": FinancialPeriod,
    "transactions": Transaction,
    "budgets": Budget,
    "vendors": Vendor,
}