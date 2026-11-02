"""Safe CSV loading.

Two guarantees matter here:

* **No arbitrary filesystem access.** Only filenames registered in the
  dataset catalog are ever resolved, and the resolved path is asserted to sit
  inside the configured data directory.
* **No unvalidated rows.** Every row is parsed into its Pydantic model, so a
  malformed number or an unexpected column fails at startup instead of
  silently poisoning an analysis.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from app.core.errors import DatasetNotFoundError, DatasetValidationError
from app.models.catalog import DATASET_CATALOG, DatasetSpec
from app.schemas.dataset import DATASET_ROW_MODELS

# Explicit dtypes keep Pandas from guessing (and from silently converting an
# identifier such as "2024-07" into something else).
DATASET_DTYPES: dict[str, dict[str, str]] = {
    "financial_data": {
        "period": "string",
        "fiscal_year": "int64",
        "quarter": "int64",
        "period_start": "string",
        "period_end": "string",
        "currency": "string",
        "revenue": "float64",
        "cogs": "float64",
        "gross_profit": "float64",
        "operating_expenses": "float64",
        "operating_income": "float64",
        "cash_operating_expenses": "float64",
        "non_cash_operating_expenses": "float64",
        "cash_begin": "float64",
        "cash_operating_cash_flow": "float64",
        "cash_investing_cash_flow": "float64",
        "cash_financing_cash_flow": "float64",
        "cash_balance": "float64",
    },
    "transactions": {
        "transaction_id": "string",
        "date": "string",
        "period": "string",
        "quarter": "string",
        "department": "string",
        "category": "string",
        "vendor_id": "string",
        "vendor": "string",
        "amount": "float64",
        "transaction_type": "string",
        "is_non_cash": "string",
        "description": "string",
    },
    "budgets": {
        "period": "string",
        "quarter": "string",
        "department": "string",
        "category": "string",
        "budget_amount": "float64",
        "actual_amount": "float64",
        "variance_amount": "float64",
        "variance_pct": "string",
        "utilisation_pct": "string",
    },
    "vendors": {
        "vendor_id": "string",
        "vendor_name": "string",
        "category": "string",
        "department": "string",
        "monthly_spend": "float64",
        "total_spend_2024": "float64",
        "transaction_count_2024": "int64",
        "avg_transaction_amount": "float64",
        "contract_type": "string",
        "contract_start": "string",
        "contract_end": "string",
        "status": "string",
    },
}

# Columns read as floats that may legitimately be blank in the source file.
OPTIONAL_NUMERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "budgets": ("variance_pct", "utilisation_pct"),
}

# Columns stored as "true"/"false" in CSV and exposed as real booleans so the
# analytics layer can mask on them safely.
BOOLEAN_COLUMNS: dict[str, tuple[str, ...]] = {
    "transactions": ("is_non_cash",),
}


def resolve_dataset_path(data_dir: Path, dataset_id: str) -> Path:
    """Return the validated path of a catalogued dataset.

    Raises :class:`DatasetNotFoundError` for anything not in the catalog, and
    refuses to return a path that escapes ``data_dir``.
    """
    spec: DatasetSpec | None = DATASET_CATALOG.get(dataset_id)
    if spec is None:
        raise DatasetNotFoundError(
            f"Unknown dataset '{dataset_id}'.",
            details={"dataset_id": dataset_id, "available": sorted(DATASET_CATALOG)},
        )

    base = data_dir.resolve()
    candidate = (base / spec.filename).resolve()
    if not candidate.is_relative_to(base):  # pragma: no cover - catalog is trusted
        raise DatasetNotFoundError(details={"dataset_id": dataset_id})
    if not candidate.is_file():
        raise DatasetNotFoundError(
            f"Dataset file '{spec.filename}' is missing.",
            details={"dataset_id": dataset_id, "filename": spec.filename},
        )
    return candidate


def load_dataframe(data_dir: Path, dataset_id: str) -> pd.DataFrame:
    """Read one catalogued CSV into a typed DataFrame.

    Every row is validated against its Pydantic model. Validation errors are
    aggregated into a single :class:`DatasetValidationError` so the operator
    sees all problems at once, with row numbers but no raw payload echo.
    """
    spec = DATASET_CATALOG[dataset_id]
    path = resolve_dataset_path(data_dir, dataset_id)

    frame = pd.read_csv(
        path,
        dtype=DATASET_DTYPES[dataset_id],
        keep_default_na=False,
        na_values=[""],
        encoding="utf-8",
    )

    expected_columns = set(DATASET_DTYPES[dataset_id])
    actual_columns = set(frame.columns)
    if expected_columns != actual_columns:
        raise DatasetValidationError(
            f"Dataset '{dataset_id}' has an unexpected column set.",
            details={
                "dataset_id": dataset_id,
                "missing_columns": sorted(expected_columns - actual_columns),
                "unexpected_columns": sorted(actual_columns - expected_columns),
            },
        )

    for column in OPTIONAL_NUMERIC_COLUMNS.get(dataset_id, ()):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    for column in BOOLEAN_COLUMNS.get(dataset_id, ()):
        frame[column] = (
            frame[column].astype("string").str.strip().str.lower().map({"true": True, "false": False})
        )

    _validate_rows(dataset_id, frame)
    return frame


def _validate_rows(dataset_id: str, frame: pd.DataFrame) -> None:
    row_model = DATASET_ROW_MODELS[dataset_id]
    errors: list[dict[str, object]] = []
    for row_number, record in enumerate(frame.to_dict(orient="records"), start=2):
        try:
            row_model.model_validate(_prepare(record))
        except ValidationError as error:
            errors.append(
                {
                    "row": row_number,
                    "fields": sorted({str(item["loc"][0]) for item in error.errors()}),
                }
            )
            if len(errors) >= 20:
                break
    if errors:
        raise DatasetValidationError(
            f"Dataset '{dataset_id}' failed row validation.",
            details={"dataset_id": dataset_id, "invalid_rows": errors},
        )

    if len(frame) < DATASET_CATALOG[dataset_id].expected_min_rows:
        raise DatasetValidationError(
            f"Dataset '{dataset_id}' has fewer rows than the catalog requires.",
            details={
                "dataset_id": dataset_id,
                "row_count": len(frame),
                "expected_min_rows": DATASET_CATALOG[dataset_id].expected_min_rows,
            },
        )


def _prepare(record: dict[str, object]) -> dict[str, object]:
    """Adapt a Pandas row to the shape the Pydantic model expects."""
    prepared: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, str):
            value = value.strip()
            if not value:
                value = None
        prepared[key] = value
    return prepared