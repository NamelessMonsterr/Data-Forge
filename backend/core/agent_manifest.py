"""Executable agent manifest used by the Planner and graph builder."""

from __future__ import annotations

from typing import Any

from backend.core.capability_cards import (
    PLANNER_CARD,
    agent_capability_card,
    all_capability_cards,
)


def all_agent_manifests(include_planner: bool = True) -> dict[str, dict[str, Any]]:
    """Return planner and registry-backed agent manifests."""
    return all_capability_cards(include_planner=include_planner)


def agent_manifest(agent_id: str) -> dict[str, Any]:
    """Return one registry-backed agent manifest."""
    return agent_capability_card(agent_id)
