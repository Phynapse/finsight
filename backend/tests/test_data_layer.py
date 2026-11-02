"""Dataset loading, integrity checks and repository behaviour."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import DatasetNotFoundError, DatasetValidationError
from app.data import integrity
from app.data.integrity import net_cash_spend
from app.data.loader import load_dataframe
from app.data.repository import DatasetRepository
from app.models.catalog import DATASET_CATALOG


class TestLoader:
    def test_every_catalogued_dataset_loads(self, repository: DatasetRepository):
        assert set(repository.datasets) == set(DATASET_CATALOG)

    def test_amounts_are_always_positive(self, repository: DatasetRepository):
        """The sign convention lives in ``transaction_type``, never in ``amount``."""
        transactions = repository.frame("transactions")
        assert (transactions["amount"] > 0).all()

    def test_credit_rows_exist(self, repository: DatasetRepository):
        transactions = repository.frame("transactions")
        assert set(transactions["transaction_type"].unique()) == {"expense", "credit"}

    def test_missing_file_is_a_typed_error(self, tmp_path):
        with pytest.raises(DatasetNotFoundError):
            load_dataframe(tmp_path, "financial_data")

    def test_unknown_dataset_is_rejected(self, repository: DatasetRepository):
        with pytest.raises(DatasetValidationError):
            repository.frame("does_not_exist")

    def test_frames_are_copies_so_callers_cannot_corrupt_the_repository(
        self, repository: DatasetRepository
    ):
        frame = repository.frame("transactions")
        frame.loc[frame.index[0], "amount"] = -1.0
        assert (repository.frame("transactions")["amount"] > 0).all()


class TestRepositoryVocabulary:
    def test_periods_are_ordered_oldest_first(self, repository: DatasetRepository):
        periods = repository.periods
        assert periods == sorted(periods)
        assert periods[0] == "2023-Q1"
        assert periods[-1] == "2024-Q4"

    def test_latest_period_is_the_final_quarter(self, repository: DatasetRepository):
        assert repository.latest_period == "2024-Q4"

    def test_months_cover_the_ledger_year(self, repository: DatasetRepository):
        """The ledger is FY2024 only; FY2023 exists in the statement alone."""
        months = repository.months
        assert len(months) == 12
        assert months[0] == "2024-01"
        assert months[-1] == "2024-12"

    def test_single_currency(self, repository: DatasetRepository):
        assert repository.currency() == "USD"

    def test_quarters_in_a_fiscal_year(self, repository: DatasetRepository):
        assert repository.quarters_in_fiscal_year(2024) == [
            "2024-Q1",
            "2024-Q2",
            "2024-Q3",
            "2024-Q4",
        ]

    def test_unloaded_repository_refuses_access(self, settings: Settings):
        empty = DatasetRepository(data_dir=settings.resolved_data_dir)
        with pytest.raises(DatasetValidationError):
            empty.frame("transactions")


class TestIntegrity:
    def test_all_checks_pass(self, repository: DatasetRepository):
        failed = [
            check.id for check in repository.integrity_checks() if not check.passed
        ]
        assert failed == []

    def test_there_are_eleven_checks(self, repository: DatasetRepository):
        assert len(repository.integrity_checks()) == 11

    def test_integrity_ok_agrees_with_the_check_list(self, repository: DatasetRepository):
        assert repository.integrity_ok() is True

    def test_a_corrupted_ledger_fails_the_tie_out(
        self, repository: DatasetRepository
    ):
        """A check must be able to fail, or it proves nothing."""
        transactions = repository.frame("transactions")
        financial = repository.frame("financial_data")
        index = transactions.index[0]
        transactions.loc[index, "amount"] = float(transactions.loc[index, "amount"]) + 1_000_000.0

        assert integrity.check_transactions_tie_to_income_statement(
            financial, transactions
        ).passed is False
        # The untouched copy still reconciles.
        assert integrity.check_transactions_tie_to_income_statement(
            repository.frame("financial_data"), repository.frame("transactions")
        ).passed is True

    def test_a_broken_statement_identity_fails_its_check(
        self, repository: DatasetRepository
    ):
        financial = repository.frame("financial_data")
        financial.loc[financial.index[0], "operating_income"] = (
            float(financial.loc[financial.index[0], "operating_income"]) + 5_000.0
        )
        assert integrity.check_income_statement_arithmetic(financial).passed is False


class TestNetCashSpend:
    def test_expenses_add_and_credits_subtract(self, repository: DatasetRepository):
        transactions = repository.frame("transactions")
        signed = net_cash_spend(transactions)
        expense_row = transactions.index[transactions["transaction_type"] == "expense"][0]
        credit_row = transactions.index[transactions["transaction_type"] == "credit"][0]
        assert signed.loc[expense_row] == pytest.approx(
            float(transactions.loc[expense_row, "amount"])
        )
        assert signed.loc[credit_row] == pytest.approx(
            -float(transactions.loc[credit_row, "amount"])
        )