"""Typed application settings for DataForge AI."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class StorageSettings:
    """Storage paths used by the local development implementation."""

    artifacts_root: Path = Path("tmp/dataforge_runs")
    state_path: Path = Path("tmp/dataforge_state.json")


@dataclass(frozen=True)
class DiscoverySettings:
    """Discovery provider settings."""

    live_enabled: bool = False
    github_token: str | None = None
    web_search_endpoint: str | None = None
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class LLMSettings:
    """LLM orchestration settings."""

    live_enabled: bool = False
    provider_priority: tuple[str, ...] = ("nim", "gemini", "openai", "ollama")
    max_retries: int = 3
    cooldown_seconds: float = 60.0
    timeout_seconds: float = 20.0
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-70b-instruct"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"


@dataclass(frozen=True)
class AppSettings:
    """Top-level DataForge application settings."""

    storage: StorageSettings = field(default_factory=StorageSettings)
    discovery: DiscoverySettings = field(default_factory=DiscoverySettings)
    llm: LLMSettings = field(default_factory=LLMSettings)


def load_env_file(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE pairs from a local env file without overriding env."""
    if os.getenv("DATAFORGE_SKIP_DOTENV", "").lower() in {"1", "true", "yes"}:
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def get_settings() -> AppSettings:
    """Return default application settings."""
    provider_priority = tuple(
        provider.strip().lower()
        for provider in os.getenv("DATAFORGE_LLM_PROVIDERS", "nim,gemini,openai,ollama").split(",")
        if provider.strip()
    )
    discovery_live = os.getenv(
        "DATAFORGE_DISCOVERY_LIVE",
        os.getenv("DATAFORGE_LIVE_DISCOVERY", ""),
    )
    return AppSettings(
        discovery=DiscoverySettings(
            live_enabled=discovery_live.lower() in {"1", "true", "yes"},
            github_token=os.getenv("GITHUB_TOKEN"),
            web_search_endpoint=os.getenv("DATAFORGE_WEB_SEARCH_ENDPOINT"),
            timeout_seconds=float(os.getenv("DATAFORGE_DISCOVERY_TIMEOUT", "5")),
        ),
        llm=LLMSettings(
            live_enabled=os.getenv("DATAFORGE_LIVE_LLM", "").lower()
            in {"1", "true", "yes"},
            provider_priority=provider_priority or ("nim", "gemini", "openai", "ollama"),
            max_retries=int(os.getenv("DATAFORGE_LLM_MAX_RETRIES", "3")),
            cooldown_seconds=float(os.getenv("DATAFORGE_LLM_COOLDOWN_SECONDS", "60")),
            timeout_seconds=float(os.getenv("DATAFORGE_LLM_TIMEOUT", "20")),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
            nvidia_base_url=os.getenv(
                "NVIDIA_NIM_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ),
            nvidia_model=os.getenv(
                "NVIDIA_NIM_MODEL",
                "meta/llama-3.1-70b-instruct",
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        ),
    )
