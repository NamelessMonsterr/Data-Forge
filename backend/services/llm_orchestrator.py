"""Provider-agnostic LLM orchestration for AI skills.

The orchestrator owns provider priority, retries, cooldown, and fallback. By
default it runs the :class:`DeterministicSkillProvider`, which produces answers
that are *computed from the supplied context* rather than canned strings -- so
offline mode stays honest and useful. When ``DATAFORGE_LIVE_LLM`` is enabled and
credentials are present, live NVIDIA NIM / OpenAI providers take priority and the
deterministic provider becomes the final safety net.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
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


# --------------------------------------------------------------------------
# Deterministic helpers (module-level so they are easy to unit test)
# --------------------------------------------------------------------------

_SYNONYMS: dict[str, list[str]] = {
    "qa": ["question", "answer", "question_answering"],
    "sentiment": ["polarity", "emotion", "opinion"],
    "medical": ["healthcare", "clinical", "biomedical"],
    "health": ["healthcare", "medical", "clinical"],
    "finance": ["financial", "fintech", "market"],
    "legal": ["law", "contract", "judicial"],
    "image": ["vision", "visual", "picture"],
    "speech": ["audio", "voice", "asr"],
    "code": ["programming", "source", "software"],
    "chat": ["dialogue", "conversation", "instruction"],
}

_DOMAIN_HINTS: dict[str, set[str]] = {
    "healthcare": {"medical", "health", "clinical", "diabetes", "patient", "healthcare"},
    "finance": {"finance", "financial", "market", "stock", "fintech", "bank"},
    "legal": {"legal", "law", "contract", "court", "judicial"},
    "climate": {"climate", "weather", "rainfall", "temperature", "emissions"},
    "mobility": {"traffic", "accident", "accidents", "transport", "mobility", "vehicle"},
    "nlp": {"chat", "qa", "sentiment", "instruction", "dialogue", "text"},
}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", str(text).lower()) if token]


def _guess_domain(tokens: list[str]) -> str:
    token_set = set(tokens)
    best, best_overlap = "general", 0
    for domain, hints in _DOMAIN_HINTS.items():
        overlap = len(token_set & hints)
        if overlap > best_overlap:
            best, best_overlap = domain, overlap
    return best


def _infer_field_role(field_name: str) -> str:
    name = field_name.lower()
    if name in {"id", "uuid", "index"} or name.endswith("_id"):
        return "identifier"
    if "instruction" in name or "prompt" in name or "question" in name:
        return "instruction"
    if "response" in name or "answer" in name or "completion" in name or "output" in name:
        return "response"
    if name in {"label", "target", "class", "category", "sentiment"} or name.endswith("_label"):
        return "label/target"
    if "date" in name or "time" in name or "year" in name:
        return "temporal"
    if "lang" in name or "language" in name:
        return "language"
    return "text"


class DeterministicSkillProvider:
    """Offline-safe provider used until live credentials are configured.

    Every answer is *derived from the request context*; there are no canned
    sentences. This keeps the demo reproducible and honest while still being
    useful, and gives live providers a meaningful fallback.
    """

    def __init__(self, name: str = "local-deterministic") -> None:
        self.name = name
        self._handlers = {
            "dataset_summary": self._dataset_summary,
            "dataset_recommendation": self._dataset_recommendation,
            "dataset_gap_analysis": self._dataset_gap_analysis,
            "schema_inference": self._schema_inference,
            "dataset_card": self._dataset_card,
            "quality_narrative": self._quality_narrative,
            "search_intent": self._search_intent,
        }

    def execute(self, request: LLMRequest) -> str:
        """Generate deterministic skill output from structured context."""
        handler = self._handlers.get(request.skill)
        if handler is not None:
            return handler(request.context)
        return f"{request.skill}: {request.prompt[:220]}"

    # -- existing skills --------------------------------------------------

    def _dataset_summary(self, context: dict[str, Any]) -> str:
        title = context.get("title", "dataset")
        rows = context.get("rows", "unknown")
        columns = context.get("columns", "unknown")
        schema = context.get("schema", {}) or {}
        stats = context.get("stats", {}) or {}
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

    # -- new skills -------------------------------------------------------

    def _dataset_gap_analysis(self, context: dict[str, Any]) -> str:
        requirement = context.get("requirement", {}) or {}
        rows = _as_int(context.get("rows"))
        min_rows = _as_int(requirement.get("min_rows") or requirement.get("target_rows"))
        have_langs = {
            str(lang).lower()
            for lang in (context.get("languages") or requirement.get("languages") or [])
        }
        want_langs = {str(lang).lower() for lang in (requirement.get("languages") or [])}
        schema = context.get("schema", {}) or {}
        fields = {str(key).lower() for key in schema}
        gaps: list[str] = []
        if min_rows and rows < min_rows:
            gaps.append(
                f"volume: {rows} of {min_rows} target rows ({min_rows - rows} short)"
            )
        missing_langs = sorted(want_langs - have_langs)
        if missing_langs:
            gaps.append("languages: missing " + ", ".join(missing_langs))
        target = str(requirement.get("target_model", "")).lower()
        instruction_like = {"instruction", "response", "prompt", "completion"}
        if target and not (instruction_like & fields):
            gaps.append(
                "format: no instruction/response columns for instruction tuning"
            )
        domain = requirement.get("domain", "the request")
        if not gaps:
            return (
                f"No material gaps detected for '{domain}'. "
                f"{rows} rows with fields {', '.join(sorted(fields)) or 'unknown'} "
                "satisfy the stated requirement; proceed to curation and skip "
                "synthetic generation."
            )
        plan = (
            "Recommended order: search additional sources for the shortfall first, "
            "then reserve synthetic generation for residual gaps only."
        )
        return "Coverage gaps detected -- " + "; ".join(gaps) + ". " + plan

    def _schema_inference(self, context: dict[str, Any]) -> str:
        schema = context.get("schema", {}) or {}
        if not schema:
            return (
                "No schema supplied; ingest the dataset to infer field roles "
                "and the likely training task."
            )
        role_map = {str(field): _infer_field_role(str(field)) for field in schema}
        roles = "; ".join(f"{field} -> {role}" for field, role in role_map.items())
        role_values = set(role_map.values())
        if {"instruction", "response"} <= role_values:
            task = "instruction tuning (supervised fine-tuning)"
        elif "label/target" in role_values:
            task = "supervised classification or regression"
        elif "text" in role_values or "instruction" in role_values:
            task = "language modeling, embeddings, or retrieval"
        else:
            task = "exploratory analysis"
        return f"Inferred field roles: {roles}. Most likely training task: {task}."

    def _dataset_card(self, context: dict[str, Any]) -> str:
        title = context.get("title", "Dataset")
        rows = context.get("rows", "unknown")
        columns = context.get("columns", "unknown")
        schema = context.get("schema", {}) or {}
        license_name = context.get("license", "unspecified")
        quality = context.get("quality_score", "Unavailable")
        tags = context.get("tags", []) or []
        summary = context.get("summary") or context.get("ai_summary") or ""
        field_lines = (
            "\n".join(f"- `{name}`: {dtype}" for name, dtype in list(schema.items())[:20])
            or "- (schema unavailable)"
        )
        tag_line = ", ".join(tags) if tags else "none"
        default_summary = f"{title} contains {rows} records across {columns} columns."
        return (
            f"# {title}\n\n"
            f"## Summary\n{summary or default_summary}\n\n"
            f"## Composition\n- Records: {rows}\n- Columns: {columns}\n- Tags: {tag_line}\n\n"
            f"## Schema\n{field_lines}\n\n"
            f"## Licensing\n- Declared license: {license_name}\n"
            "- Verify redistribution terms before commercial use.\n\n"
            f"## Quality\n- Weighted quality score: {quality}\n\n"
            "## Intended Use\nDiscovery, exploratory analysis, prototyping, and packaging.\n\n"
            "## Limitations\nMetrics are computed by deterministic heuristics unless "
            "live LLM mode is enabled; validate domain coverage before production training."
        )

    def _quality_narrative(self, context: dict[str, Any]) -> str:
        metrics = context.get("metrics", {}) or {}
        score = context.get("score", "Unavailable")
        threshold = context.get("threshold")
        profile = context.get("profile", "production")
        if not metrics:
            return (
                f"Quality score {score} for the {profile} profile; per-dimension "
                "metrics were not supplied."
            )
        ordered = sorted(
            ((str(key), _as_float(value)) for key, value in metrics.items()),
            key=lambda item: item[1],
        )
        weakest, strongest = ordered[0], ordered[-1]
        verdict = ""
        if isinstance(threshold, (int, float)) and isinstance(score, (int, float)):
            meets = score >= threshold
            tail = (
                ""
                if meets
                else ", so search-first remediation or targeted generation is advised"
            )
            verdict = (
                f" The dataset {'meets' if meets else 'falls short of'} the "
                f"{profile} threshold of {threshold}{tail}."
            )
        return (
            f"Overall weighted quality is {score} on a 0-100 scale for the "
            f"{profile} profile. Strongest dimension: {strongest[0]} "
            f"({_fmt(strongest[1])}). Weakest dimension: {weakest[0]} "
            f"({_fmt(weakest[1])})." + verdict
        )

    def _search_intent(self, context: dict[str, Any]) -> str:
        query = str(context.get("query", "")).strip()
        if not query:
            return "Empty query; provide search terms to expand intent."
        tokens = _tokens(query)
        expanded: list[str] = []
        for token in tokens:
            expanded.extend(_SYNONYMS.get(token, []))
        domain = _guess_domain(tokens)
        terms = sorted(set(tokens) | set(expanded))
        filters: list[str] = []
        if any(token in tokens for token in ("recent", "latest", "2024", "2025")):
            filters.append("freshness=recent")
        if domain != "general":
            filters.append(f"domain={domain}")
        return (
            f"Normalized intent terms: {', '.join(terms)}. "
            f"Likely domain: {domain}. "
            f"Suggested filters: {', '.join(filters) if filters else 'none'}."
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
                        "Return concise, decision-useful prose grounded only in "
                        "the supplied context."
                    ),
                },
                {"role": "user", "content": self._prompt(request)},
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
            provider.name: ProviderHealth() for provider in self.providers
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
                    {"provider": provider.name, "status": "skipped", "reason": "cooldown"}
                )
                continue
            for attempt in range(1, self.max_retries + 1):
                try:
                    text = provider.execute(request)
                except Exception as exc:  # noqa: BLE001 - recorded as an attempt
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
                    {"provider": provider.name, "attempt": attempt, "status": "success"}
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
        # Deterministic provider is always the final safety net.
        providers.append(DeterministicSkillProvider())
        return providers

    def status(self) -> dict[str, Any]:
        """Return provider priority and health state."""
        active = self.providers[0].name if self.providers else None
        return {
            "provider_priority": [provider.name for provider in self.providers],
            "active_provider": active,
            "mode": "offline_deterministic"
            if active == "local-deterministic"
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
