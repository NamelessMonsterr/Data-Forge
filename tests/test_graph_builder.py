"""Capability resolver and graph builder tests."""

from backend.core.graph_builder import CapabilityResolver, DependencyGraphBuilder


def test_capability_resolver_finds_agent_by_capability_tag():
    """Resolver should map capability tags to registry agents."""
    selection = CapabilityResolver().find_capability("multilingual_translation")

    assert selection.agent == "translation"
    assert selection.capability == "multilingual_translation"


def test_dependency_graph_builder_resolves_dependencies():
    """Graph builder should include required dependencies and validate output."""
    result = DependencyGraphBuilder().build(
        ["multilingual_translation", "quality_scoring", "benchmarking", "zip_export"],
        workflow_name="test_capability_graph",
    )
    nodes = [node.value for node in result.workflow.nodes]

    assert result.validation_errors == ()
    assert "translation" in nodes
    assert "curator" in nodes
    assert "packaging" in nodes
    assert nodes.index("curator") < nodes.index("translation")
    assert nodes.index("formatter") < nodes.index("packaging")
    assert result.estimated_cost > 0
