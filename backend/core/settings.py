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
class AppSettings:
    """Top-level DataForge application settings."""

    storage: StorageSettings = field(default_factory=StorageSettings)
    discovery: DiscoverySettings = field(default_factory=DiscoverySettings)


def get_settings() -> AppSettings:
    """Return default application settings."""
    return AppSettings(
        discovery=DiscoverySettings(
            live_enabled=os.getenv("DATAFORGE_LIVE_DISCOVERY", "").lower()
            in {"1", "true", "yes"},
            github_token=os.getenv("GITHUB_TOKEN"),
            web_search_endpoint=os.getenv("DATAFORGE_WEB_SEARCH_ENDPOINT"),
            timeout_seconds=float(os.getenv("DATAFORGE_DISCOVERY_TIMEOUT", "5")),
        )
    )
