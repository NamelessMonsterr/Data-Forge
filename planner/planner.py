"""Rule-based planner that selects only frozen Workflow Library entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from planner.graph_validator import validate_graph
from planner.workflow_library import OPTIONAL_NODES, WORKFLOW_LIBRARY, Mutation, Node, Workflow


@dataclass(frozen=True)
class PlannerMutation:
    """Machine-readable legal mutation applied to a workflow."""

    action: str
    agent: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        """Return a serializable mutation payload."""
        return {
            "action": self.action,
            "agent": self.agent,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlanningResult:
    """Validated planner output ready for execution."""

    workflow: Workflow
    validation_errors: tuple[str, ...]
    rationale: str
    structured_requirement: dict[str, Any]
    mutations: tuple[PlannerMutation, ...] = ()
    confidence: float = 0.0
    alternatives: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        """Return whether the selected workflow passed graph validation."""
        return not self.validation_errors


class RuleBasedPlanner:
    """Select a base workflow from the frozen library using transparent rules."""

    def plan(self, request: dict[str, Any]) -> PlanningResult:
        """Analyze a user request and return a validated Workflow Library choice."""
        structured = self._structure_requirement(request)
        workflow_key, rationale = self._select_workflow(structured)
        workflow, mutations = self._apply_legal_mutations(
            WORKFLOW_LIBRARY[workflow_key],
            structured,
        )
        errors = tuple(validate_graph(workflow))
        alternatives = self._alternatives(workflow_key, structured)
        return PlanningResult(
            workflow=workflow,
            validation_errors=errors,
            rationale=rationale,
            structured_requirement=structured,
            mutations=mutations,
            confidence=self._confidence(structured, workflow_key, mutations, errors),
            alternatives=alternatives,
        )

    def _structure_requirement(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(
            request.get("request")
            or request.get("query")
            or request.get("goal")
            or request.get("prompt")
            or ""
        ).strip()
        lowered = text.lower()
        languages = [
            language
            for language in ("english", "hindi", "spanish", "french", "german")
            if language in lowered
        ]
        domains = [
            domain
            for domain in ("healthcare", "legal", "finance", "education", "code")
            if domain in lowered
        ]
        return {
            "raw_request": text,
            "purpose": request.get("purpose", "fine_tuning"),
            "domain": domains[0] if domains else request.get("domain", "general"),
            "languages": languages or request.get("languages", ["english"]),
            "quality_profile": request.get("quality_profile", "production"),
            "output_format": request.get("output_format", "jsonl"),
            "target_model": request.get("target_model", "nemotron"),
            "requires_generation": any(
                marker in lowered
                for marker in (
                    "synthetic",
                    "generate",
                    "gap",
                    "rare",
                    "edge case",
                    "no existing",
                )
            ),
            "search_only": any(
                marker in lowered
                for marker in ("search only", "find datasets", "discover datasets", "candidate datasets")
            ),
            "cleaning_only": any(
                marker in lowered
                for marker in ("clean only", "cleaning only", "clean dataset", "remove duplicates")
            ),
            "search_first": True,
        }

    def _select_workflow(self, structured: dict[str, Any]) -> tuple[str, str]:
        if structured["search_only"]:
            return (
                "dataset_search_only",
                "Request only needs dataset discovery and license filtering, so downstream data processing agents are not scheduled.",
            )
        if structured["requires_generation"] and "no existing" in structured["raw_request"].lower():
            return (
                "generate_only",
                "Request explicitly indicates no usable existing data, so the last-resort generation workflow was selected from the library.",
            )
        if structured["requires_generation"]:
            return (
                "full_search_improve_generate_export",
                "Request indicates a likely data gap, so the full search-improve workflow runs first and generation is added only as a last-resort fill step.",
            )
        if len(structured["languages"]) > 1:
            return (
                "multilingual_dataset",
                "Request includes multiple languages, so curation runs before translation and only retained records are translated.",
            )
        if structured["cleaning_only"]:
            return (
                "clean_quality_export",
                "Request focuses on cleaning, so the Planner selected the cleaning and quality workflow without translation or generation.",
            )
        return (
            "full_search_improve_export",
            "No explicit data gap was detected, so the full search, license, merge, clean, translate, curate, validate, benchmark, report, and export workflow was selected.",
        )

    def _apply_legal_mutations(
        self,
        workflow: Workflow,
        structured: dict[str, Any],
    ) -> tuple[Workflow, tuple[PlannerMutation, ...]]:
        nodes = list(workflow.nodes)
        mutations: list[PlannerMutation] = []

        if Node.TRANSLATION in nodes and len(structured["languages"]) <= 1:
            nodes.remove(Node.TRANSLATION)
            mutations.append(
                PlannerMutation(
                    action=Mutation.REMOVE_OPTIONAL_AGENT.value,
                    agent=Node.TRANSLATION.value,
                    reason="single_language_request",
                )
            )

        if Node.BIAS in nodes and structured["quality_profile"] == "fast":
            nodes.remove(Node.BIAS)
            mutations.append(
                PlannerMutation(
                    action=Mutation.REMOVE_OPTIONAL_AGENT.value,
                    agent=Node.BIAS.value,
                    reason="fast_quality_profile",
                )
            )

        illegal_removals = [
            mutation
            for mutation in mutations
            if mutation.agent not in {node.value for node in OPTIONAL_NODES}
        ]
        if illegal_removals:
            return workflow, tuple()

        return (
            Workflow(
                name=workflow.name,
                description=workflow.description,
                nodes=tuple(nodes),
            ),
            tuple(mutations),
        )

    def _alternatives(
        self,
        selected_workflow: str,
        structured: dict[str, Any],
    ) -> tuple[str, ...]:
        candidates = [
            "dataset_search_only",
            "clean_quality_export",
            "multilingual_dataset",
            "full_search_improve_export",
            "full_search_improve_generate_export",
            "generate_only",
        ]
        return tuple(
            name
            for name in candidates
            if name != selected_workflow and name in WORKFLOW_LIBRARY
        )[:3]

    def _confidence(
        self,
        structured: dict[str, Any],
        workflow_key: str,
        mutations: tuple[PlannerMutation, ...],
        errors: tuple[str, ...],
    ) -> float:
        if errors:
            return 0.0
        confidence = 0.78
        if structured["domain"] != "general":
            confidence += 0.06
        if structured["languages"]:
            confidence += 0.04
        if workflow_key in {
            "dataset_search_only",
            "multilingual_dataset",
            "generate_only",
            "clean_quality_export",
        }:
            confidence += 0.06
        if mutations:
            confidence += 0.03
        return min(round(confidence, 2), 0.96)
