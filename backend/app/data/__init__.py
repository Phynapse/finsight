"""Data access layer: safe CSV loading, integrity checks, in-memory repository."""

from app.data.loader import load_dataframe, resolve_dataset_path
from app.data.repository import DatasetRepository, RepositorySnapshot

__all__ = [
    "DatasetRepository",
    "RepositorySnapshot",
    "load_dataframe",
    "resolve_dataset_path",
]