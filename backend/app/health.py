"""Liveness and readiness checks wired to real dependency probes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

Check = Callable[[], bool]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


class HealthService:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._checks: dict[str, Check] = {}
        self._clock = clock
        self._started = clock()

    def register(self, name: str, check: Check) -> None:
        self._checks[name] = check

    def liveness(self) -> dict:
        return {"status": "alive", "uptime_seconds": round(self._clock() - self._started, 3)}

    def readiness(self) -> dict:
        results: list[CheckResult] = []
        for name, check in self._checks.items():
            try:
                ok = bool(check())
                results.append(CheckResult(name, ok, "" if ok else "check returned false"))
            except Exception as exc:  # dependency failure must not crash the probe
                results.append(CheckResult(name, False, str(exc)))
        ready = all(r.ok for r in results)
        return {
            "status": "ready" if ready else "unready",
            "checks": [r.__dict__ for r in results],
        }


def make_sqlite_check(repository) -> Check:
    def _check() -> bool:
        repository.list_datasets()
        return True

    return _check
