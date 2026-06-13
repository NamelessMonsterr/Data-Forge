"""Execution engine tests for production discovery behavior."""

from pathlib import Path

from backend.core.execution import ExecutionEngine
from planner.planner import RuleBasedPlanner


def _run(request: dict, tmp_path: Path):
    plan = RuleBasedPlanner().plan(request)
    return ExecutionEngine(artifacts_root=tmp_path).execute(
        plan.workflow,
        request,
        {
            "structured_requirement": plan.structured_requirement,
            "planner_rationale": plan.rationale,
        },
    )


def test_execution_engine_aborts_cleanly_when_discovery_is_disabled(tmp_path: Path):
    """Production offline discovery should not fabricate candidates for packaging."""
    result = _run(
        {"request": "I need a Hindi-English instruction dataset for healthcare."},
        tmp_path,
    )

    assert result.status == "aborted"
    assert result.artifacts == {}
    assert [message.agent for message in result.messages] == [
        "requirement_analyzer",
        "clarification",
        "discovery",
        "license",
    ]
    assert result.state["candidate_datasets"] == []
    assert result.state["discovery_status"]["enabled"] is False
    assert result.state["license_verdict"] == "rejected"


def test_generation_workflow_aborts_before_generation_without_candidates(tmp_path: Path):
    """Generator should not run when discovery/license gates have no candidates."""
    result = _run(
        {"request": "Generate rare healthcare edge cases after search."},
        tmp_path,
    )

    assert result.status == "aborted"
    assert "generator" not in [message.agent for message in result.messages]
    assert result.state["candidate_datasets"] == []


def test_search_only_workflow_does_not_package_fabricated_metadata(tmp_path: Path):
    """Search-only workflows should not create artifacts from invented candidates."""
    result = _run(
        {"request": "Find datasets for healthcare candidate datasets only."},
        tmp_path,
    )

    assert result.status == "aborted"
    assert result.workflow == "dataset_search_only"
    assert result.artifacts == {}
    assert result.state["candidate_datasets"] == []


def test_workflow_stops_at_license_gate_without_approved_candidates(tmp_path: Path):
    """The license hard gate should stop the workflow before downstream agents."""
    result = _run(
        {"request": "I need a Hindi-English instruction dataset for healthcare."},
        tmp_path,
    )

    agents = [message.agent for message in result.messages]
    assert agents == ["requirement_analyzer", "clarification", "discovery", "license"]
    assert "merge" not in agents
    assert "benchmark" not in agents
    assert result.state["license_decisions"] == []
