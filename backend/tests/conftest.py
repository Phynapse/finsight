"""Shared fixtures.

The tests run against the real bundled dataset rather than a mock, because the
point of the analytics layer is that its numbers are reproducible. Regenerating
the data with ``python scripts/generate_data.py`` must not require test changes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.data.repository import DatasetRepository
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(app_env="test", log_level="WARNING")


@pytest.fixture(scope="session")
def repository(settings: Settings) -> DatasetRepository:
    repo = DatasetRepository(data_dir=settings.resolved_data_dir)
    repo.load()
    return repo


@pytest.fixture(scope="session")
def client(settings: Settings):
    """A TestClient with the application lifespan running."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def api(client: TestClient) -> str:
    return "/api/v1"