"""Graph Validator tests - the frozen rules must hold."""

from planner.graph_validator import validate_graph
from planner.workflow_library import WORKFLOW_LIBRARY, Node, Workflow


def test_all_library_workflows_are_valid():
    for wf in WORKFLOW_LIBRARY.values():
        assert validate_graph(wf) == [], f"{wf.name} must be valid"


def test_missing_mandatory_validator_is_rejected():
    wf = Workflow(
        name="bad_no_validator",
        description="validation removed - must be rejected",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.CURATOR,
            Node.QUALITY_EVALUATOR,
            Node.FORMATTER,
            Node.PACKAGING,
        ),
    )
    errors = validate_graph(wf)
    assert any("validator" in e for e in errors)


def test_generator_without_critic_is_rejected():
    wf = Workflow(
        name="bad_unchecked_generation",
        description="synthetic data must face the critic",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.GENERATOR,
            Node.VALIDATOR,
            Node.QUALITY_EVALUATOR,
            Node.FORMATTER,
            Node.PACKAGING,
        ),
    )
    errors = validate_graph(wf)
    assert any("critic" in e for e in errors)


def test_license_must_run_before_curator():
    wf = Workflow(
        name="bad_ordering",
        description="curation before license check - must be rejected",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.CURATOR,
            Node.LICENSE,
            Node.QUALITY_EVALUATOR,
            Node.VALIDATOR,
            Node.FORMATTER,
            Node.PACKAGING,
        ),
    )
    errors = validate_graph(wf)
    assert any("Ordering violation" in e for e in errors)


def test_duplicate_node_is_rejected():
    wf = Workflow(
        name="bad_duplicate",
        description="same node twice - must be rejected",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.CURATOR,
            Node.CURATOR,
            Node.QUALITY_EVALUATOR,
            Node.VALIDATOR,
            Node.FORMATTER,
            Node.PACKAGING,
        ),
    )
    errors = validate_graph(wf)
    assert any("Duplicate" in e for e in errors)
