"""Per-user credential resolution for live provider calls.

Precedence: the user's encrypted vault key first, then the environment/global
key, then offline (labeled deterministic) when neither exists. This keeps
per-user settings authoritative while letting an admin/global deployment key
serve users who haven't configured their own, and keeps the product usable
(never failing a search/analysis flow) when no live credentials are available.

Decryption happens here on the backend ONLY -- secrets are never returned to the
client. Pass the request's authenticated ``user`` and the ``ProviderVault``
(or ``None`` when the vault is not configured, e.g. DATAFORGE_VAULT_KEY unset).

The vault provider names map to live consumers as:
  * LLM    -> ``DATAFORGE_LLM_PROVIDER`` (default ``nvidia``); api_key -> Bearer
  * Kaggle -> ``kaggle`` (api_key = username, secret = key)
  * HF     -> ``huggingface`` (api_key = access token)
"""

from __future__ import annotations

import dataclasses
import os
from typing import Optional, Tuple

from backend.vault import VaultCryptoError, VaultError

from .discovery import (
    DataGovProvider,
    DiscoveryService,
    HuggingFaceProvider,
    KaggleProvider,
    WebSearchProvider,
)
from .llm_orchestrator import (
    DeterministicSkillProvider,
    LLMOrchestrator as SkillLLMOrchestrator,
    OpenAICompatibleProvider as SkillHttpProvider,
)
from .llm_provider import LLMConfig, LLMOrchestrator

DEFAULT_LLM_PROVIDER = "nvidia"


def _env(env: Optional[dict]) -> dict:
    return env if env is not None else dict(os.environ)


def _vault_secrets(vault, user, provider) -> Optional[dict]:
    """Backend-only decrypt of a user's stored credential, or None.

    Any expected vault failure (no vault, no user, unknown provider, malformed
    blob) degrades to ``None`` so env/offline fallback can take over instead of
    breaking the request path.
    """
    if vault is None or user is None:
        return None
    try:
        return vault.get_secrets(user, provider)
    except (VaultError, VaultCryptoError):
        return None


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _provider_key_for(user, vault, env: dict, provider: str) -> str:
    """Resolve one provider key using vault first, then env/global keys."""
    normalized = provider.strip().lower()
    vault_provider = "nvidia" if normalized in {"nim", "nvidia"} else normalized
    secrets = _vault_secrets(vault, user, vault_provider)
    if secrets and secrets.get("api_key"):
        return secrets["api_key"]
    if normalized in {"nim", "nvidia"}:
        return env.get("NVIDIA_API_KEY") or env.get("DATAFORGE_LLM_API_KEY") or ""
    if normalized == "openai":
        return env.get("OPENAI_API_KEY") or ""
    return ""


def llm_config_for(user, vault, env=None, provider=None) -> LLMConfig:
    """Resolve an ``LLMConfig`` for this user (vault key -> env key -> offline)."""
    e = _env(env)
    base = LLMConfig.from_env(e)
    name = (provider or e.get("DATAFORGE_LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()
    secrets = _vault_secrets(vault, user, name)
    user_key = secrets.get("api_key") if secrets else None
    api_key = user_key or base.api_key
    # Go live only if explicitly enabled AND a key is actually available;
    # otherwise degrade to the labeled offline/deterministic path rather than
    # calling a provider with no credentials.
    live = base.live and bool(api_key)
    return dataclasses.replace(base, api_key=api_key, live=live)


def build_llm_orchestrator_for(user, vault, env=None, provider=None, **kwargs) -> LLMOrchestrator:
    """Construct an ``LLMOrchestrator`` using this user's resolved LLM config."""
    return LLMOrchestrator(
        config=llm_config_for(user, vault, env=env, provider=provider), **kwargs
    )


def build_skill_orchestrator_for(user, vault, env=None) -> SkillLLMOrchestrator:
    """Construct the AI-skills orchestrator with user vault credentials first.

    This is the resolver for ``backend.services.ai_skills`` and catalog outputs.
    It mirrors the default skills orchestrator provider behavior, but resolves
    keys per request: user vault -> env/global key -> labeled deterministic.
    """
    e = _env(env)
    if not _truthy(e.get("DATAFORGE_LIVE_LLM")):
        return SkillLLMOrchestrator()

    providers = []
    priority = [
        item.strip().lower()
        for item in e.get("DATAFORGE_LLM_PROVIDERS", "nim,gemini,openai,ollama").split(",")
        if item.strip()
    ]
    timeout = float(e.get("DATAFORGE_LLM_TIMEOUT", "20"))
    for provider_name in priority:
        if provider_name in {"nim", "nvidia"}:
            api_key = _provider_key_for(user, vault, e, "nvidia")
            if api_key:
                providers.append(
                    SkillHttpProvider(
                        name="nim",
                        api_key=api_key,
                        base_url=e.get(
                            "NVIDIA_NIM_BASE_URL",
                            e.get(
                                "DATAFORGE_LLM_BASE_URL",
                                "https://integrate.api.nvidia.com/v1",
                            ),
                        ),
                        model=e.get(
                            "NVIDIA_NIM_MODEL",
                            e.get(
                                "DATAFORGE_LLM_MODEL",
                                "meta/llama-3.1-8b-instruct",
                            ),
                        ),
                        timeout_seconds=timeout,
                    )
                )
        elif provider_name == "openai":
            api_key = _provider_key_for(user, vault, e, "openai")
            if api_key:
                providers.append(
                    SkillHttpProvider(
                        name="openai",
                        api_key=api_key,
                        base_url=e.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                        model=e.get("OPENAI_MODEL", "gpt-4o-mini"),
                        timeout_seconds=timeout,
                    )
                )

    providers.append(DeterministicSkillProvider())
    return SkillLLMOrchestrator(
        providers=providers,
        max_retries=int(e.get("DATAFORGE_LLM_MAX_RETRIES", "3")),
        cooldown_seconds=float(e.get("DATAFORGE_LLM_COOLDOWN_SECONDS", "60")),
    )


def kaggle_creds_for(user, vault, env=None) -> Tuple[str, str]:
    """Return (username, key) from the vault, else from the environment."""
    secrets = _vault_secrets(vault, user, "kaggle")
    if secrets and secrets.get("api_key"):
        return secrets["api_key"], (secrets.get("secret") or "")
    e = _env(env)
    return e.get("KAGGLE_USERNAME", ""), e.get("KAGGLE_KEY", "")


def huggingface_token_for(user, vault, env=None) -> str:
    """Return an HF access token from the vault, else from the environment."""
    secrets = _vault_secrets(vault, user, "huggingface")
    if secrets and secrets.get("api_key"):
        return secrets["api_key"]
    e = _env(env)
    return e.get("HUGGINGFACE_TOKEN") or e.get("HF_TOKEN") or ""


def build_discovery_service_for(user, vault, env=None, client=None) -> DiscoveryService:
    """Construct a ``DiscoveryService`` with this user's resolved provider creds."""
    e = _env(env)
    username, key = kaggle_creds_for(user, vault, env=e)
    hf_token = huggingface_token_for(user, vault, env=e)
    providers = [
        HuggingFaceProvider(client=client, token=hf_token or None),
        WebSearchProvider(client=client),
        DataGovProvider(client=client),
        KaggleProvider(client=client, username=username, key=key),
    ]
    return DiscoveryService(providers=providers, env=e)
