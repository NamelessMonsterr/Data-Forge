"""Agent registry metadata tests."""

from backend.core.registry import AGENT_REGISTRY


def test_registry_exposes_dependency_and_cost_metadata():
    """Every registry-backed agent should expose planning metadata."""
    for name, spec in AGENT_REGISTRY.items():
        summary = spec.summary()
        assert summary["category"]
        assert isinstance(summary["requires"], list)
        assert isinstance(summary["produces"], list)
        assert summary["estimated_cost"] >= 1
        assert summary["estimated_runtime_seconds"] >= 1

    assert "curator" in AGENT_REGISTRY["translation"].summary()["requires"]
    assert "dataset_zip" in AGENT_REGISTRY["packaging"].summary()["produces"]
