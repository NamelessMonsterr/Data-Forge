"""Execution engine tests for the hackathon vertical slice."""

from pathlib import Path
from zipfile import ZipFile

from backend.core.execution import ExecutionEngine
from planner.planner import RuleBasedPlanner


def test_execution_engine_creates_dataset_zip(tmp_path: Path):
    """A valid workflow should produce reports and a dataset ZIP."""
    request = {"request": "I need a Hindi-English instruction dataset for healthcare."}
    plan = RuleBasedPlanner().plan(request)
    result = ExecutionEngine(artifacts_root=tmp_path).execute(
        plan.workflow,
        request,
        {
            "structured_requirement": plan.structured_requirement,
            "planner_rationale": plan.rationale,
        },
    )

    zip_path = Path(result.artifacts["dataset_zip"])
    assert result.status == "completed"
    assert zip_path.exists()
    assert [message.next_action.value for message in result.messages]
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "dataset.jsonl" in names
    assert "dataset_card.md" in names
    assert "dataset_card.json" in names
    assert "manifest.json" in names
    assert "reports/dataset_intelligence_report.md" in names
    assert "reports/explainability_report.md" in names
    assert "reports/benchmark_report.md" in names


def test_execution_engine_uses_generation_only_for_gap_workflow(tmp_path: Path):
    """The generator should run only for a workflow that includes it."""
    request = {"request": "Generate rare healthcare edge cases after search."}
    plan = RuleBasedPlanner().plan(request)
    result = ExecutionEngine(artifacts_root=tmp_path).execute(
        plan.workflow,
        request,
        {
            "structured_requirement": plan.structured_requirement,
            "planner_rationale": plan.rationale,
        },
    )

    assert result.status == "completed"
    assert "generator" in [message.agent for message in result.messages]
    assert result.state["synthetic_samples_added"] == 1


def test_execution_engine_exports_search_only_candidate_metadata(tmp_path: Path):
    """Search-only workflows should package approved candidate metadata."""
    request = {"request": "Find datasets for healthcare candidate datasets only."}
    plan = RuleBasedPlanner().plan(request)
    result = ExecutionEngine(artifacts_root=tmp_path).execute(
        plan.workflow,
        request,
        {
            "structured_requirement": plan.structured_requirement,
            "planner_rationale": plan.rationale,
        },
    )

    assert result.status == "completed"
    assert result.workflow == "dataset_search_only"
    assert result.state["validation_report"]["mode"] == "metadata"
    assert Path(result.artifacts["dataset_zip"]).exists()
    assert result.state["manifest"].endswith("manifest.json")
    assert result.state["checksums"]


def test_execution_engine_runs_full_platform_agents(tmp_path: Path):
    """The multilingual workflow should include core registry workers but keep reports as services."""
    request = {"request": "I need a Hindi-English instruction dataset for healthcare."}
    plan = RuleBasedPlanner().plan(request)
    result = ExecutionEngine(artifacts_root=tmp_path).execute(
        plan.workflow,
        request,
        {
            "structured_requirement": plan.structured_requirement,
            "planner_rationale": plan.rationale,
        },
    )

    agents = [message.agent for message in result.messages]
    assert "merge" in agents
    assert "cleaning" in agents
    assert "translation" in agents
    assert "bias" in agents
    assert "critic" in agents
    assert "benchmark" in agents
    assert "reporter" not in agents
    assert result.state["benchmark_report"]["training_readiness"] == "PASS"
    assert result.state["license_decisions"]
    assert all(
        decision["status"] == "APPROVED"
        for decision in result.state["license_decisions"]
        if decision["compatible"]
    )
