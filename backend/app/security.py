"""API hardening: API-key auth, request size limits, token-bucket rate limiting,
and environment-driven CORS, composed into a single ``SecurityPolicy``.

The policy is pure and fully unit-tested. ``build_security_middleware`` lazily
imports Starlette/FastAPI so importing this module never requires the web
framework (keeps the tested core stdlib-only).
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: int = 200
    reason: str = ""


class ApiKeyAuth:
    def __init__(self, keys) -> None:
        self.keys = [k.strip() for k in keys if k.strip()]

    @property
    def enabled(self) -> bool:
        return bool(self.keys)

    def check(self, presented: str | None) -> bool:
        if not self.enabled:
            return True  # allow-all when no keys configured (dev)
        if not presented:
            return False
        return any(hmac.compare_digest(presented, k) for k in self.keys)


class TokenBucketRateLimiter:
    def __init__(self, capacity: int = 60, refill_per_sec: float = 1.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, client_id: str) -> bool:
        with self._lock:
            now = self._clock()
            tokens, last = self._buckets.get(client_id, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens < 1:
                self._buckets[client_id] = (tokens, now)
                return False
            self._buckets[client_id] = (tokens - 1, now)
            return True


@dataclass
class RequestLimits:
    max_body_bytes: int = 10 * 1024 * 1024

    def check_size(self, body_size: int) -> Decision:
        if body_size > self.max_body_bytes:
            return Decision(False, 413, "payload too large")
        return Decision(True)


@dataclass
class SecurityConfig:
    api_keys: list
    max_body_bytes: int
    rate_capacity: int
    rate_refill: float
    cors_origins: list

    @classmethod
    def from_env(cls, env: dict | None = None) -> "SecurityConfig":
        env = env if env is not None else dict(os.environ)
        keys = [k.strip() for k in env.get("DATAFORGE_API_KEYS", "").split(",") if k.strip()]
        origins = [
            o.strip()
            for o in env.get("DATAFORGE_CORS_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ]
        return cls(
            api_keys=keys,
            max_body_bytes=int(env.get("DATAFORGE_MAX_BODY_BYTES", str(10 * 1024 * 1024))),
            rate_capacity=int(env.get("DATAFORGE_RATE_CAPACITY", "60")),
            rate_refill=float(env.get("DATAFORGE_RATE_REFILL", "1.0")),
            cors_origins=origins,
        )


class SecurityPolicy:
    public_paths = ("/health", "/ready")

    def __init__(self, config: SecurityConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self.auth = ApiKeyAuth(config.api_keys)
        self.limits = RequestLimits(config.max_body_bytes)
        self.rate = TokenBucketRateLimiter(config.rate_capacity, config.rate_refill, clock)

    def cors_origins(self) -> list:
        return list(self.config.cors_origins)

    def evaluate(self, path: str, api_key: str | None, body_size: int, client_id: str) -> Decision:
        if path in self.public_paths:
            return Decision(True)
        size = self.limits.check_size(body_size)
        if not size.allowed:
            return size
        if not self.auth.check(api_key):
            return Decision(False, 401, "invalid or missing API key")
        if not self.rate.allow(client_id):
            return Decision(False, 429, "rate limit exceeded")
        return Decision(True)


def build_security_middleware(config: SecurityConfig | None = None):
    """Lazily construct a Starlette/FastAPI middleware class."""
    from starlette.middleware.base import BaseHTTPMiddleware  # imported lazily
    from starlette.responses import JSONResponse

    cfg = config or SecurityConfig.from_env()
    policy = SecurityPolicy(cfg)

    class SecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            body = await request.body()
            client = request.client.host if request.client else "anon"
            decision = policy.evaluate(
                request.url.path, request.headers.get("x-api-key"), len(body), client
            )
            if not decision.allowed:
                return JSONResponse({"error": decision.reason}, status_code=decision.status)
            return await call_next(request)

    return SecurityMiddleware
