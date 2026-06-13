"""Pagination and a small TTL cache for search/catalog at volume."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable


def paginate(items: Iterable[Any], page: int = 1, page_size: int = 20) -> dict[str, Any]:
    materialized = list(items)
    total = len(materialized)
    page_size = max(1, min(page_size, 200))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    window = materialized[start : start + page_size]
    return {
        "items": window,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


class TTLCache:
    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 512,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._store: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self.max_entries and key not in self._store:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest, None)
            self._store[key] = (self._clock() + self.ttl, value)

    def get_or_set(self, key: Any, producer: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = producer()
        self.set(key, value)
        return value

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
