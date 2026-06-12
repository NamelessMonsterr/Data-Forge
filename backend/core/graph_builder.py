"""Capability-based graph builder for DataForge workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.agent_manifest import all_agent_manifests
from planner.graph_validator import validate_graph
from planner.workflow_library import Node, ORDERING_RULES, Workflow


@dataclass(frozen=True)
class CapabilitySelection:
    """Resolved agent for a requested capability."""

    capability: str
    agent: str
    reason: str


@dataclass(frozen=True)
class GraphBuildResult:
    """Capability-built workflow and planning metadata."""

    workflow: Workflow
    selections: tuple[CapabilitySelection, ...]
    estimated_cost: int
    estimated_runtime_seconds: int
    validation_errors: tuple[str, ...]


class CapabilityResolver:
    """Resolve capability tags to registry-backed agent manifests."""

    def __init__(self, manifests: dict[str, dict[str, Any]] | None = None) -> None:
        self.manifests = manifests or all_agent_manifests(include_planner=False)

    def find_capability(
        self,
        capability: str,
        optimization: str = "balanced",
    ) -> CapabilitySelection:
        """Return the best agent for a capability tag."""
        matches = [
            manifest
            for manifest in self.manifests.values()
            if capability in manifest.get("capabilities", [])
        ]
        if not matches:
            raise ValueError(f"No agent provides capability: {capability}")
        selected = self._rank(matches, optimization)[0]
        return CapabilitySelection(
            capability=capability,
            agent=selected["id"],
            reason=f"Selected {selected['id']} for {capability} using {optimization} optimization.",
        )

    def _rank(
        self,
        manifests: list[dict[str, Any]],
        optimization: str,
    ) -> list[dict[str, Any]]:
        if optimization == "fast":
            return sorted(manifests, key=lambda item: item["estimated_runtime_seconds"])
        if optimization == "cheap":
            return sorted(manifests, key=lambda item: item["estimated_cost"])
        return sorted(
            manifests,
            key=lambda item: (
                item["estimated_cost"],
                item["estimated_runtime_seconds"],
            ),
        )


class DependencyGraphBuilder:
    """Build validated workflows from capability requirements."""

    def __init__(
        self,
        resolver: CapabilityResolver | None = None,
        manifests: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.manifests = manifests or all_agent_manifests(include_planner=False)
        self.resolver = resolver or CapabilityResolver(self.manifests)

    def build(
        self,
        required_capabilities: list[str],
        workflow_name: str = "capability_graph",
        optimization: str = "balanced",
    ) -> GraphBuildResult:
        """Build a workflow from required capability tags."""
        selections = tuple(
            self.resolver.find_capability(capability, optimization)
            for capability in required_capabilities
        )
        selected_agents = {selection.agent for selection in selections}
        resolved_agents = self._with_dependencies(selected_agents)
        ordered_agents = self._topological_sort(resolved_agents)
        nodes = tuple(Node(agent) for agent in ordered_agents)
        workflow = Workflow(
            name=workflow_name,
            description="Capability-built workflow generated from agent manifests.",
            nodes=nodes,
        )
        errors = tuple(validate_graph(workflow))
        return GraphBuildResult(
            workflow=workflow,
            selections=selections,
            estimated_cost=sum(self.manifests[agent]["estimated_cost"] for agent in ordered_agents),
            estimated_runtime_seconds=sum(
                self.manifests[agent]["estimated_runtime_seconds"]
                for agent in ordered_agents
            ),
            validation_errors=errors,
        )

    def _with_dependencies(self, agents: set[str]) -> set[str]:
        resolved = set(agents)
        changed = True
        while changed:
            changed = False
            for agent in list(resolved):
                for dependency in self.manifests[agent].get("requires", []):
                    if dependency not in resolved:
                        resolved.add(dependency)
                        changed = True
        return resolved

    def _topological_sort(self, agents: set[str]) -> list[str]:
        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(agent: str) -> None:
            if agent in visited:
                return
            if agent in visiting:
                raise ValueError(f"Cycle detected at agent: {agent}")
            visiting.add(agent)
            dependencies = set(self.manifests[agent].get("requires", []))
            dependencies.update(
                earlier.value
                for earlier, later in ORDERING_RULES
                if later.value == agent and earlier.value in agents
            )
            for dependency in dependencies:
                if dependency in agents:
                    visit(dependency)
            visiting.remove(agent)
            visited.add(agent)
            ordered.append(agent)

        for agent in sorted(agents):
            visit(agent)
        return ordered
