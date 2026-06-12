"""Planner tests for deterministic workflow selection."""

from planner.planner import RuleBasedPlanner


def test_planner_selects_search_first_workflow_by_default():
    """A multilingual dataset request should use the multilingual workflow."""
    result = RuleBasedPlanner().plan(
        {"request": "I need a Hindi-English instruction dataset for healthcare."}
    )

    assert result.is_valid
    assert result.workflow.name == "multilingual_dataset"
    assert result.structured_requirement["domain"] == "healthcare"
    assert result.structured_requirement["search_first"] is True
    assert result.confidence >= 0.9
    assert result.alternatives


def test_planner_selects_gap_fill_workflow_for_explicit_generation_need():
    """The full generation workflow is selected only when a gap is signaled."""
    result = RuleBasedPlanner().plan(
        {"request": "I need rare healthcare edge case samples; generate only if gaps remain."}
    )

    assert result.is_valid
    assert result.workflow.name == "full_search_improve_generate_export"
    assert result.structured_requirement["requires_generation"] is True


def test_planner_selects_search_only_workflow():
    """Search-only requests should avoid processing agents."""
    result = RuleBasedPlanner().plan(
        {"request": "Find datasets for healthcare candidate datasets only."}
    )

    assert result.is_valid
    assert result.workflow.name == "dataset_search_only"
    assert "merge" not in [node.value for node in result.workflow.nodes]


def test_planner_applies_legal_optional_mutations():
    """Single-language requests should remove optional translation."""
    result = RuleBasedPlanner().plan(
        {"request": "I need an English healthcare instruction dataset."}
    )
    nodes = [node.value for node in result.workflow.nodes]

    assert result.is_valid
    assert result.workflow.name == "full_search_improve_export"
    assert "translation" not in nodes
    assert any(
        mutation.to_dict()
        == {
            "action": "remove_optional_agent",
            "agent": "translation",
            "reason": "single_language_request",
        }
        for mutation in result.mutations
    )


def test_planner_selects_generate_only_when_no_existing_data_is_explicit():
    """Generate-only remains a library workflow, not free-form planning."""
    result = RuleBasedPlanner().plan(
        {"request": "No existing data is usable; generate rare synthetic legal samples."}
    )

    assert result.is_valid
    assert result.workflow.name == "generate_only"
