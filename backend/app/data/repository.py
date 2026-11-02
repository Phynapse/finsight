"""In-memory dataset repository.

The repository is the only place that owns DataFrames. Analytics receive it as
a read-only dependency and never touch the filesystem, never build a path from
user input, and never see a raw unvalidated row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from app.core.errors import DatasetValidationError
from app.core.logging import get_logger
from app.data import integrity
from app.data.loader import load_dataframe
from app.models.catalog import DATASET_CATALOG, DatasetSpec
from app.schemas.dataset_api import DatasetSummary

logger = get_logger(__name__)

# Period columns per dataset, used for summaries and for range filtering.
PERIOD_COLUMNS: Mapping[str, str] = MappingProxyType(
    {
        "financial_data": "period",
        "transactions": "period",
        "budgets": "period",
        "vendors": "contract_start",
    }
)


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Immutable-by-convention view of one dataset."""

    dataset_id: str
    spec: DatasetSpec
    frame: pd.DataFrame
    row_count: int
    file_size_bytes: int


@dataclass
class DatasetRepository:
    """Loads, validates and serves the bundled datasets."""

    data_dir: Path
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict, init=False)
    _snapshots: dict[str, RepositorySnapshot] = field(default_factory=dict, init=False)
    _loaded: bool = field(default=False, init=False)

    # -- lifecycle ----------------------------------------------------------
    def load(self) -> None:
        """Load and validate every catalogued dataset. Idempotent."""
        if self._loaded:
            return
        frames: dict[str, pd.DataFrame] = {}
        snapshots: dict[str, RepositorySnapshot] = {}
        for dataset_id, spec in DATASET_CATALOG.items():
            frame = load_dataframe(self.data_dir, dataset_id)
            frames[dataset_id] = frame
            snapshots[dataset_id] = RepositorySnapshot(
                dataset_id=dataset_id,
                spec=spec,
                frame=frame,
                row_count=len(frame),
                file_size_bytes=int((self.data_dir / spec.filename).stat().st_size),
            )
            logger.info("loaded dataset %s (%s rows)", dataset_id, len(frame))
        self._frames = frames
        self._snapshots = snapshots
        self._loaded = True

    def require_loaded(self) -> None:
        if not self._loaded:
            raise DatasetValidationError("Datasets have not been loaded yet.")

    # -- access -------------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def dataset_count(self) -> int:
        return len(self._frames)

    @property
    def datasets(self) -> tuple[str, ...]:
        """Registered dataset ids, in catalog order."""
        return tuple(self._frames)

    def frame(self, dataset_id: str) -> pd.DataFrame:
        """Return a copy of a dataset so callers cannot mutate shared state."""
        self.require_loaded()
        try:
            frame = self._frames[dataset_id]
        except KeyError as error:
            raise DatasetValidationError(
                f"Dataset '{dataset_id}' is not registered.", details={"dataset_id": dataset_id}
            ) from error
        return frame.copy(deep=False)

    def snapshot(self, dataset_id: str) -> RepositorySnapshot:
        self.require_loaded()
        return self._snapshots[dataset_id]

    def has(self, dataset_id: str) -> bool:
        return dataset_id in self._frames

    # -- domain vocabularies -------------------------------------------------
    @property
    def periods(self) -> list[str]:
        """Fiscal quarters present in the income statement, oldest first."""
        self.require_loaded()
        return sorted(self._frames["financial_data"]["period"].tolist())

    @property
    def months(self) -> list[str]:
        """Distinct month keys present in the ledger, oldest first.

        Distinct matters: callers index into and slice this list to resolve a
        period range, so a repeated value would silently misplace the range.
        """
        self.require_loaded()
        return sorted(self._frames["transactions"]["period"].dropna().unique().tolist())

    @property
    def latest_period(self) -> str:
        return self.periods[-1]

    def quarters_in_fiscal_year(self, fiscal_year: int) -> list[str]:
        return [period for period in self.periods if period.startswith(f"{fiscal_year}-Q")]

    def departments(self) -> list[str]:
        self.require_loaded()
        return sorted(self._frames["transactions"]["department"].dropna().unique().tolist())

    def categories(self) -> list[str]:
        self.require_loaded()
        return sorted(self._frames["transactions"]["category"].dropna().unique().tolist())

    def vendor_ids(self) -> list[str]:
        self.require_loaded()
        return sorted(self._frames["vendors"]["vendor_id"].tolist())

    def currency(self) -> str:
        self.require_loaded()
        currencies = self._frames["financial_data"]["currency"].dropna().unique().tolist()
        return currencies[0] if len(currencies) == 1 else "mixed"

    # -- integrity ----------------------------------------------------------
    def integrity_checks(self) -> list:
        """Run every cross-dataset assertion and return the results."""
        self.require_loaded()
        financial = self._frames["financial_data"]
        transactions = self._frames["transactions"]
        budgets = self._frames["budgets"]
        vendors = self._frames["vendors"]
        return [
            integrity.check_income_statement_arithmetic(financial),
            integrity.check_opex_cash_split(financial),
            integrity.check_cash_roll_forward(financial),
            integrity.check_cash_continuity(financial),
            integrity.check_transactions_tie_to_income_statement(financial, transactions),
            integrity.check_budgets_tie_to_transactions(transactions, budgets),
            integrity.check_budget_derived_columns(budgets),
            integrity.check_vendor_rollup(transactions, vendors),
            integrity.check_vendor_foreign_keys(transactions, vendors),
            integrity.check_period_alignment(financial, transactions, budgets),
            integrity.check_unique_keys(financial, transactions, budgets, vendors),
        ]

    def integrity_ok(self) -> bool:
        return all(check.passed for check in self.integrity_checks())

    # -- summaries ----------------------------------------------------------
    def summary(self, dataset_id: str) -> DatasetSummary:
        snapshot = self.snapshot(dataset_id)
        frame = snapshot.frame
        period_column = PERIOD_COLUMNS[dataset_id]
        if dataset_id == "financial_data":
            periods = sorted(frame["period"].tolist())
        else:
            periods = sorted(frame[period_column].dropna().astype(str).unique().tolist())

        from app.models.catalog import metrics_for_dataset

        relevant_checks = [
            check for check in self.integrity_checks() if dataset_id in check.datasets
        ]
        return DatasetSummary(
            id=dataset_id,
            label=snapshot.spec.label,
            description=snapshot.spec.description,
            grain=snapshot.spec.grain,
            row_grain_label=snapshot.spec.row_grain_label,
            primary_key=list(snapshot.spec.primary_key),
            row_count=snapshot.row_count,
            column_count=len(frame.columns),
            columns=[
                {
                    "name": str(column),
                    "dtype": str(frame[column].dtype),
                    "nullable": bool(frame[column].isna().any()),
                    "description": "",
                }
                for column in frame.columns
            ],
            period_start=periods[0] if periods else None,
            period_end=periods[-1] if periods else None,
            period_count=len(periods),
            available_periods=periods[:60],
            metrics=[metric.id for metric in metrics_for_dataset(dataset_id)],
            integrity_checks=relevant_checks,
        )