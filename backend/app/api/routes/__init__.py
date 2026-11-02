"""API route modules, mounted under the configured prefix by :mod:`app.main`."""

from app.api.routes import analysis, catalog, datasets, questions, system

__all__ = ["analysis", "catalog", "datasets", "questions", "system"]