"""Hybrid API Router for provider selection, failover, and execution memory.

Routes every LLM-requiring agent to the most suitable provider.
NIM is preferred; Groq, Gemini, OpenAI and Ollama MUST all work (GPU-credit insurance).

Failover semantics (frozen):
  quota exceeded  -> switch PROVIDER
  timeout         -> switch PROVIDER
  poor quality    -> switch MODEL
  unavailable     -> Planner chooses backup
Every switch is recorded by the Auditor.

Execution memory belongs to the Router. The local implementation stores provider stats
in memory; the same interface can be backed by Redis without changing Planner code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Protocol


class Provider(str, Enum):
    NIM = "nim"
    GROQ = "groq"
    GEMINI = "gemini"
    OPENAI = "openai"
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    TOGETHER = "together"
    HUGGINGFACE = "huggingface"
    CUSTOM = "custom"


class RoutingPolicy(str, Enum):
    FASTEST = "fastest"
    CHEAPEST = "cheapest"
    HIGHEST_QUALITY = "highest_quality"
    BALANCED = "balanced"
    PRIVACY = "privacy"
    CUSTOM_PRIORITY = "custom_priority"


#: Default failover chain. NIM preferred; the rest are mandatory fallbacks.
DEFAULT_FAILOVER_CHAIN: tuple[Provider, ...] = (
    Provider.NIM,
    Provider.GROQ,
    Provider.GEMINI,
    Provider.OPENAI,
    Provider.OLLAMA,
)


@dataclass
class ProviderStats:
    """Execution memory entry (persisted in Redis, keyed by provider)."""

    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    unavailable_count: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total else 1.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.success_count if self.success_count else 0.0

    @property
    def failure_rate(self) -> float:
        """Return provider failure rate."""
        total = self.success_count + self.failure_count
        return self.failure_count / total if total else 0.0

    def record_success(self, latency_ms: float, cost_usd: float) -> None:
        """Record a successful provider call."""
        self.success_count += 1
        self.total_latency_ms += latency_ms
        self.total_cost_usd += cost_usd

    def record_failure(self, unavailable: bool = False) -> None:
        """Record a failed provider call."""
        self.failure_count += 1
        if unavailable:
            self.unavailable_count += 1


@dataclass(frozen=True)
class RouterRequest:
    """Provider-agnostic request passed through the router."""

    agent: str
    prompt: str
    max_tokens: int = 512


@dataclass(frozen=True)
class RouterResponse:
    """Provider-agnostic response returned by the router."""

    provider: Provider
    text: str
    latency_ms: float
    cost_usd: float


@dataclass(frozen=True)
class RouterDecision:
    """Auditable record of a router decision."""

    provider: Provider
    reason: str
    policy: RoutingPolicy


class ProviderClient(Protocol):
    """Provider client interface implemented by concrete model providers."""

    provider: Provider

    def complete(self, request: RouterRequest) -> RouterResponse:
        """Execute a completion request."""
        ...


class OfflineProviderClient:
    """Offline-safe provider client used until real credentials are configured."""

    def __init__(self, provider: Provider, cost_per_call_usd: float = 0.001) -> None:
        self.provider = provider
        self.cost_per_call_usd = cost_per_call_usd

    def complete(self, request: RouterRequest) -> RouterResponse:
        """Return a deterministic provider response for local development."""
        started = perf_counter()
        text = f"[{self.provider.value}] {request.agent}: {request.prompt[:160]}"
        latency_ms = (perf_counter() - started) * 1000
        return RouterResponse(
            provider=self.provider,
            text=text,
            latency_ms=latency_ms,
            cost_usd=self.cost_per_call_usd,
        )


class HybridRouter:
    """Route LLM requests through provider clients with auditable failover."""

    def __init__(
        self,
        policy: RoutingPolicy = RoutingPolicy.BALANCED,
        chain: tuple[Provider, ...] = DEFAULT_FAILOVER_CHAIN,
        clients: dict[Provider, ProviderClient] | None = None,
    ) -> None:
        self.policy = policy
        self.chain = chain
        self.stats: dict[Provider, ProviderStats] = {p: ProviderStats() for p in chain}
        self.clients = clients or {p: OfflineProviderClient(p) for p in chain}
        self.decisions: list[RouterDecision] = []

    def select_provider(self) -> Provider:
        """Pick the next provider according to policy + execution memory."""
        ranked = self._ranked_chain()
        for provider in ranked:
            stats = self.stats[provider]
            if stats.success_rate >= 0.5 and stats.unavailable_count < 3:
                self.decisions.append(
                    RouterDecision(
                        provider=provider,
                        reason="Provider has acceptable success rate and availability.",
                        policy=self.policy,
                    )
                )
                return provider
        fallback = ranked[-1]
        self.decisions.append(
            RouterDecision(
                provider=fallback,
                reason="All providers are degraded; using final failover provider.",
                policy=self.policy,
            )
        )
        return fallback

    def complete(self, request: RouterRequest) -> RouterResponse:
        """Execute a request, failing over across providers on errors."""
        last_error: Exception | None = None
        for provider in self._ranked_chain():
            client = self.clients[provider]
            try:
                response = client.complete(request)
            except Exception as exc:
                self.stats[provider].record_failure(unavailable=True)
                last_error = exc
                continue
            self.stats[provider].record_success(
                response.latency_ms,
                response.cost_usd,
            )
            self.decisions.append(
                RouterDecision(
                    provider=provider,
                    reason="Provider completed request successfully.",
                    policy=self.policy,
                )
            )
            return response
        raise RuntimeError("All router providers failed") from last_error

    def status(self) -> dict:
        """Return serializable router status and execution memory."""
        return {
            "policy": self.policy.value,
            "failover_chain": [provider.value for provider in self.chain],
            "selected_provider": self.select_provider().value,
            "provider_stats": {
                provider.value: {
                    "success_rate": stats.success_rate,
                    "failure_rate": stats.failure_rate,
                    "avg_latency_ms": stats.avg_latency_ms,
                    "success_count": stats.success_count,
                    "failure_count": stats.failure_count,
                    "unavailable_count": stats.unavailable_count,
                    "total_cost_usd": stats.total_cost_usd,
                }
                for provider, stats in self.stats.items()
            },
            "decisions": [
                {
                    "provider": decision.provider.value,
                    "reason": decision.reason,
                    "policy": decision.policy.value,
                }
                for decision in self.decisions
            ],
        }

    def _ranked_chain(self) -> tuple[Provider, ...]:
        if self.policy is RoutingPolicy.FASTEST:
            return tuple(
                sorted(
                    self.chain,
                    key=lambda provider: self.stats[provider].avg_latency_ms or 0.0,
                )
            )
        if self.policy is RoutingPolicy.CHEAPEST:
            return tuple(
                sorted(
                    self.chain,
                    key=lambda provider: self.stats[provider].total_cost_usd,
                )
            )
        if self.policy is RoutingPolicy.HIGHEST_QUALITY:
            return tuple(
                sorted(
                    self.chain,
                    key=lambda provider: self.stats[provider].success_rate,
                    reverse=True,
                )
            )
        if self.policy is RoutingPolicy.PRIVACY:
            ordered = [provider for provider in self.chain if provider is Provider.OLLAMA]
            ordered.extend(provider for provider in self.chain if provider is not Provider.OLLAMA)
            return tuple(ordered)
        for provider in self.chain:
            if provider not in self.stats:
                self.stats[provider] = ProviderStats()
        return self.chain
