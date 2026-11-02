"""Bounded in-memory store for completed analyses.

Phase 1 deliberately has no database. Analyses live in a small, TTL-bounded
dictionary so ``GET /analysis/{id}`` works for a demo while memory stays flat
under load: the store evicts the oldest entry once it reaches its cap and drops
anything older than its TTL on read.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.errors import AnalysisNotFoundError
from app.schemas.analysis import AnalysisResult


@dataclass
class _Entry:
    stored_at: datetime
    value: AnalysisResult


class AnalysisStore:
    """Thread-safe, size- and time-bounded analysis store."""

    def __init__(self, max_items: int = 100, ttl_seconds: int = 3_600) -> None:
        self.max_items = max_items
        self.ttl = timedelta(seconds=ttl_seconds)
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, analysis_id: str, result: AnalysisResult) -> None:
        with self._lock:
            self._purge_expired()
            self._entries[analysis_id] = _Entry(
                stored_at=datetime.now(timezone.utc), value=result
            )
            self._entries.move_to_end(analysis_id)
            while len(self._entries) > self.max_items:
                self._entries.popitem(last=False)

    def get(self, analysis_id: str) -> AnalysisResult:
        with self._lock:
            entry = self._entries.get(analysis_id)
            if entry is None:
                raise AnalysisNotFoundError(
                    details={"analysis_id": analysis_id, "ttl_seconds": int(self.ttl.total_seconds())}
                )
            if self._is_expired(entry):
                self._entries.pop(analysis_id, None)
                raise AnalysisNotFoundError(details={"analysis_id": analysis_id})
            return entry.value

    def ids(self) -> list[str]:
        with self._lock:
            self._purge_expired()
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # -- internals ----------------------------------------------------------
    def _is_expired(self, entry: _Entry) -> bool:
        return datetime.now(timezone.utc) - entry.stored_at > self.ttl

    def _purge_expired(self) -> None:
        for key in [key for key, entry in self._entries.items() if self._is_expired(entry)]:
            self._entries.pop(key, None)