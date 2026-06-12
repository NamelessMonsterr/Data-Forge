"""Graph Validator - runs BEFORE every execution. Invalid graph -> Planner regenerates.

Checks (frozen):
  - no unknown node types
  - no duplicate execution of the same node
  - mandatory nodes present (validation can never be removed)
  - ordering rules respected (e.g. license check before curation)
  - required companions present (e.g. generator implies critic + validator)

The MVP executes linear sequences, so cycle detection is structural: a repeated node
in the sequence is a duplicate/cycle violation. When the engine moves to true DAGs,
extend with DFS cycle detection.
"""

from __future__ import annotations

from planner.workflow_library import (
    MANDATORY_NODES,
    ORDERING_RULES,
    REQUIRED_COMPANIONS,
    Node,
    Workflow,
)


def validate_graph(workflow: Workflow) -> list[str]:
    """Return a list of human-readable violations. Empty list == valid graph."""
    errors: list[str] = []
    nodes = list(workflow.nodes)
    node_set = set(nodes)

    # Unknown node types (defense in depth - Node enum already constrains this)
    for n in nodes:
        if not isinstance(n, Node):
            errors.append(f"Unknown node type: {n!r}")

    # Duplicate execution / structural cycle
    if len(nodes) != len(node_set):
        seen: set[Node] = set()
        for n in nodes:
            if n in seen:
                errors.append(f"Duplicate execution of node: {n.value}")
            seen.add(n)

    # Mandatory nodes (validation can never be removed)
    for required in MANDATORY_NODES:
        if required not in node_set:
            errors.append(f"Mandatory node missing: {required.value}")

    # Ordering rules (only enforced when both nodes are present)
    index = {n: i for i, n in enumerate(nodes)}
    for earlier, later in ORDERING_RULES:
        if earlier in index and later in index and index[earlier] > index[later]:
            errors.append(
                f"Ordering violation: {earlier.value} must run before {later.value}"
            )

    # Required companions (e.g. generator implies critic + validator)
    for node, companions in REQUIRED_COMPANIONS.items():
        if node in node_set:
            for companion in companions:
                if companion not in node_set:
                    errors.append(
                        f"{node.value} requires companion node: {companion.value}"
                    )

    return errors
