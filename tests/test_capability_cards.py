"""Capability card tests."""

from backend.core.capability_cards import all_capability_cards
from backend.core.registry import AGENT_REGISTRY


REQUIRED_CARD_FIELDS = {
    "id",
    "version",
    "category",
    "optional",
    "parallelizable",
    "mission",
    "inputs",
    "outputs",
    "tools",
    "constraints",
    "success",
    "failure",
    "capabilities",
    "requires",
    "produces",
    "reads",
    "writes",
    "events",
    "quality_targets",
    "llm_required",
    "gpu_required",
    "estimated_cost",
    "estimated_runtime_seconds",
}


def test_agent_capability_cards_cover_registry_agents():
    """Every registry agent should have a complete capability card."""
    cards = all_capability_cards(include_planner=False)

    assert set(cards) == set(AGENT_REGISTRY)
    for card in cards.values():
        assert REQUIRED_CARD_FIELDS.issubset(card)
        assert card["registry_agent"] is True
        assert card["mission"]
        assert card["tools"]["required"] is not None
        assert card["failure"]["returns"]
        assert set(card["writes"]).intersection(set(card["produces"]))


def test_planner_card_is_not_registry_agent():
    """Planner should be documented as an orchestrator, not a registry worker."""
    cards = all_capability_cards(include_planner=True)

    assert "planner" in cards
    assert "planner" not in AGENT_REGISTRY
    assert cards["planner"]["registry_agent"] is False
    assert cards["planner"]["category"] == "orchestration"
