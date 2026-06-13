"""Structured JSON logging, request-id propagation, and lightweight metrics.

``configure_logging`` installs exactly one DataForge JSON handler (rebuilt on
each call so it honors the provided ``stream``). Request IDs flow via a
contextvar. ``MetricsRegistry`` provides counters, histograms (with p95), a
``timed`` context manager, and ``track_provider`` for LLM primary/fallback rates.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def new_request_id() -> str:
    rid = uuid.uuid4().hex
    _request_id.set(rid)
    return rid


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def get_request_id() -> str:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": get_request_id(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO, stream=None) -> logging.Handler:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_dataforge", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(stream)
    handler._dataforge = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    return handler


def log_event(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})


@dataclass
class Histogram:
    _samples: list = field(default_factory=list)
    _cap: int = 1000

    def observe(self, value: float) -> None:
        self._samples.append(value)
        if len(self._samples) > self._cap:
            self._samples.pop(0)

    def snapshot(self) -> dict:
        s = sorted(self._samples)
        if not s:
            return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0, "p95": 0.0}
        count = len(s)
        total = sum(s)
        idx = min(count - 1, int(round(0.95 * (count - 1))))
        return {
            "count": count,
            "sum": total,
            "min": s[0],
            "max": s[-1],
            "avg": total / count,
            "p95": s[idx],
        }


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = Lock()

    def incr(self, name: str, by: float = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def counter(self, name: str) -> float:
        return self._counters.get(name, 0)

    def histogram(self, name: str) -> Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram()
            return self._histograms[name]

    @contextmanager
    def timed(self, name: str, clock: Callable[[], float] = time.monotonic):
        start = clock()
        try:
            yield
        finally:
            self.histogram(name).observe(clock() - start)

    def track_provider(self, provider: str, fallback_used: bool) -> None:
        self.incr(f"llm.calls.{provider}")
        self.incr("llm.fallback" if fallback_used else "llm.primary")

    def snapshot(self) -> dict:
        return {
            "counters": dict(self._counters),
            "histograms": {k: v.snapshot() for k, v in self._histograms.items()},
        }


REGISTRY = MetricsRegistry()
