"""Provider-agnostic LLM orchestration for AI skills."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from time import monotonic
from typing import Any, Protocol

import httpx

from backend.core.settings import get_settings


@dataclass(frozen=True)
class LLMRequest:
    """Skill request sent to the LLM orchestrator."""

    skill: str
    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 512


@dataclass(frozen=True)
class LLMResponse:
    """Provider-agnostic LLM response."""

    provider: str
    text: str
    attempts: tuple[dict[str, Any], ...]
    fallback_used: bool


class LLMProvider(Protocol):
    """Interface implemented by concrete LLM providers."""

    name: str

    def execute(self, request: LLMRequest) -> str:
        """Return generated text for a skill request."""
        ...


@dataclass
class ProviderHealth:
    """In-memory health state for one provider."""

    success_count: int = 0
    failure_count: int = 0
    unavailable_until: float = 0.0

    def available(self, now: float) -> bool:
        return now >= self.unavailable_until


class DeterministicSkillProvider:
    """Offline-safe provider used until real credentials are configured."""

    def __init__(self, name: str = "local-deterministic") -> None:
        self.name = name

    def execute(self, request: LLMRequest) -> str:
        """Generate deterministic skill outputs from structured context."""
        if request.skill == "dataset_summary":
            return self._dataset_summary(request.context)
        if request.skill == "dataset_recommendation":
            return self._dataset_recommendation(request.context)
        return f"{request.skill}: {request.prompt[:220]}"

    def _dataset_summary(self, context: dict[str, Any]) -> str:
        title = context.get("title", "dataset")
        rows = context.get("rows", "unknown")
        columns = context.get("columns", "unknown")
        schema = context.get("schema", {})
        stats = context.get("stats", {})
        field_names = ", ".join(list(schema.keys())[:8]) or "Unavailable"
        missing = stats.get("missing_cells", "Unavailable")
        duplicates = stats.get("duplicate_rows", "Unavailable")
        return (
            f"{title} contains {rows} records across {columns} columns. "
            f"Key fields include {field_names}. "
            f"The upload has {missing} missing values and {duplicates} duplicate rows, "
            "making it suitable for quick dataset inspection, search, and packaging."
        )

    def _dataset_recommendation(self, context: dict[str, Any]) -> str:
        title = context.get("title", "dataset")
        query = context.get("query", "the requested task")
        matched = ", ".join(context.get("matched_terms", [])) or "metadata relevance"
        quality = context.get("quality_score", "Unavailable")
        rows = context.get("rows", "unknown")
        return (
            f"{title} is recommended for '{query}' because it matches {matched}, "
            f"contains {rows} rows, and has a quality score of {quality}."
        )


class OpenAICompatibleProvider:
    """HTTP provider for OpenAI-compatible chat-completion APIs."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def execute(self, request: LLMRequest) -> str:
        """Execute a skill request against a chat-completions endpoint."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are DataForge's dataset intelligence layer. "
                        "Return concise, decision-useful prose grounded only in the supplied context."
                    ),
                },
                {
                    "role": "user",
                    "content": self._prompt(request),
                },
            ],
            "max_tokens": request.max_tokens,
            "temperature": 0.2,
        }
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        return str(body["choices"][0]["message"]["content"]).strip()

    def _prompt(self, request: LLMRequest) -> str:
        return (
            f"Skill: {request.skill}\n"
            f"Task: {request.prompt}\n"
            f"Context JSON:\n{json.dumps(request.context, indent=2, sort_keys=True)}"
        )


class LLMOrchestrator:
    """Retry and fallback layer shared by AI skills."""

    def __init__(
        self,
        providers: list[LLMProvider] | None = None,
        *,
        max_retries: int | None = None,
        cooldown_seconds: float | None = None,
    ) -> None:
        settings = get_settings().llm
        self.providers = providers or self._default_providers(settings)
        self.max_retries = max_retries or settings.max_retries
        self.cooldown_seconds = cooldown_seconds or settings.cooldown_seconds
        self.health: dict[str, ProviderHealth] = {
            provider.name: ProviderHealth()
            for provider in self.providers
        }

    def run(self, request: LLMRequest) -> LLMResponse:
        """Run a skill request through provider retries and fallback."""
        attempts: list[dict[str, Any]] = []
        first_provider = self.providers[0].name if self.providers else ""
        last_error: Exception | None = None
        for provider in self.providers:
            health = self.health.setdefault(provider.name, ProviderHealth())
            if not health.available(monotonic()):
                attempts.append(
                    {
                        "provider": provider.name,
                        "status": "skipped",
                        "reason": "cooldown",
                    }
                )
                continue
            for attempt in range(1, self.max_retries + 1):
                try:
                    text = provider.execute(request)
                except Exception as exc:
                    last_error = exc
                    health.failure_count += 1
                    attempts.append(
                        {
                            "provider": provider.name,
                            "attempt": attempt,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
                    if attempt == self.max_retries:
                        health.unavailable_until = monotonic() + self.cooldown_seconds
                    continue
                health.success_count += 1
                attempts.append(
                    {
                        "provider": provider.name,
                        "attempt": attempt,
                        "status": "success",
                    }
                )
                return LLMResponse(
                    provider=provider.name,
                    text=text,
                    attempts=tuple(attempts),
                    fallback_used=provider.name != first_provider,
                )
        raise RuntimeError("All LLM providers failed") from last_error

    def _default_providers(self, settings: Any) -> list[LLMProvider]:
        providers: list[LLMProvider] = []
        if not settings.live_enabled:
            return [DeterministicSkillProvider()]
        for provider_name in settings.provider_priority:
            if provider_name == "nim" and settings.nvidia_api_key:
                providers.append(
                    OpenAICompatibleProvider(
                        name="nim",
                        api_key=settings.nvidia_api_key,
                        base_url=settings.nvidia_base_url,
                        model=settings.nvidia_model,
                        timeout_seconds=settings.timeout_seconds,
                    )
                )
            elif provider_name == "openai" and settings.openai_api_key:
                providers.append(
                    OpenAICompatibleProvider(
                        name="openai",
                        api_key=settings.openai_api_key,
                        base_url=settings.openai_base_url,
                        model=settings.openai_model,
                        timeout_seconds=settings.timeout_seconds,
                    )
                )
        if not providers:
            providers.append(DeterministicSkillProvider())
        return providers

    def status(self) -> dict[str, Any]:
        """Return provider priority and health state."""
        return {
            "provider_priority": [provider.name for provider in self.providers],
            "active_provider": self.providers[0].name if self.providers else None,
            "mode": "offline_deterministic"
            if self.providers and self.providers[0].name == "local-deterministic"
            else "live_provider",
            "max_retries": self.max_retries,
            "cooldown_seconds": self.cooldown_seconds,
            "health": {
                name: {
                    "success_count": health.success_count,
                    "failure_count": health.failure_count,
                    "available": health.available(monotonic()),
                }
                for name, health in self.health.items()
            },
        }
