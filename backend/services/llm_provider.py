"""Real LLM provider with resilient transport + deterministic fallback.

- ``HttpLLMProvider`` calls a chat-completions endpoint with timeout, bounded
  retries + backoff, a circuit breaker (cooldown after repeated failures), and
  malformed-response handling.
- ``DeterministicProvider`` is the labeled offline fallback.
- ``LLMOrchestrator`` runs the live provider first (when configured) and falls
  back to deterministic, labeling the result.

The transport is injectable so the live path is fully contract-tested without
network or secrets.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    fallback_used: bool = False
    attempts: int = 1


@dataclass(frozen=True)
class LLMConfig:
    live: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = "meta/llama-3.1-8b-instruct"
    timeout: float = 30.0
    max_retries: int = 2

    @classmethod
    def from_env(cls, env: dict | None = None) -> "LLMConfig":
        env = env if env is not None else dict(os.environ)
        return cls(
            live=env.get("DATAFORGE_LIVE_LLM", "false").strip().lower() == "true",
            base_url=env.get("DATAFORGE_LLM_BASE_URL", ""),
            api_key=env.get("DATAFORGE_LLM_API_KEY", ""),
            model=env.get("DATAFORGE_LLM_MODEL", "meta/llama-3.1-8b-instruct"),
            timeout=float(env.get("DATAFORGE_LLM_TIMEOUT", "30")),
            max_retries=int(env.get("DATAFORGE_LLM_MAX_RETRIES", "2")),
        )


class Transport(Protocol):
    def post(self, url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]: ...


class UrllibTransport:
    def post(self, url, headers, body, timeout):
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            return exc.code, exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:  # pragma: no cover - network path
            raise LLMError(f"transport error: {exc.reason}") from exc


class DeterministicProvider:
    name = "local-deterministic"

    def generate(self, prompt: str, max_tokens: int = 512) -> LLMResult:
        head = " ".join(prompt.split()[:40])
        return LLMResult(text=f"[deterministic] {head}", provider=self.name, attempts=1)


class HttpLLMProvider:
    name = "live-http"

    def __init__(
        self,
        config: LLMConfig,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibTransport()
        self._clock = clock
        self._sleep = sleep
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._cooldown_until = 0.0

    @property
    def in_cooldown(self) -> bool:
        return self._clock() < self._cooldown_until

    def generate(self, prompt: str, max_tokens: int = 512) -> LLMResult:
        if self.in_cooldown:
            raise LLMError("circuit open: provider in cooldown")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        attempts = 0
        last_err = "unknown"
        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                status, text = self.transport.post(url, headers, body, self.config.timeout)
            except LLMError as exc:
                last_err = str(exc)
                self._backoff(attempts)
                continue
            if status == 200:
                content = self._parse(text)
                if content is None:
                    raise self._fail("malformed response", attempts)
                self._consecutive_failures = 0
                return LLMResult(text=content, provider=self.name, attempts=attempts)
            if status == 429 or status >= 500:
                last_err = f"status {status}"
                self._backoff(attempts)
                continue
            raise self._fail(f"status {status}", attempts)  # 4xx: no retry
        raise self._fail(last_err, attempts)

    def _backoff(self, attempts: int) -> None:
        self._sleep(0.05 * (2 ** (attempts - 1)))

    def _parse(self, text: str):
        try:
            return json.loads(text)["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            return None

    def _fail(self, reason: str, attempts: int) -> LLMError:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._cooldown_until = self._clock() + self.cooldown_seconds
        return LLMError(f"{reason} after {attempts} attempt(s)")


class LLMOrchestrator:
    def __init__(
        self,
        config: LLMConfig | None = None,
        primary=None,
        fallback=None,
        env: dict | None = None,
    ) -> None:
        self.config = config or LLMConfig.from_env(env)
        self.fallback = fallback or DeterministicProvider()
        if primary is not None:
            self.primary = primary
        elif self.config.live:
            self.primary = HttpLLMProvider(self.config)
        else:
            self.primary = None

    def generate(self, prompt: str, max_tokens: int = 512) -> LLMResult:
        if self.primary is not None:
            try:
                return self.primary.generate(prompt, max_tokens)
            except LLMError:
                r = self.fallback.generate(prompt, max_tokens)
                return LLMResult(r.text, r.provider, fallback_used=True, attempts=r.attempts)
        return self.fallback.generate(prompt, max_tokens)
