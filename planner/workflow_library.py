"""Workflow Library - FROZEN planning model.

The Planner NEVER invents graphs from scratch. It:
  1. Selects a base workflow from this library
  2. Applies LEGAL mutations only
  3. Passes the result through the Graph Validator
  4. Regenerates if invalid

Legal mutations:   insert agent | remove OPTIONAL agent | replace equivalent agent |
                   reorder safe nodes
Illegal:           new node types | cycles | removing mandatory validation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Node(str, Enum):
    """The ONLY legal node types. The Planner cannot create new ones."""

    REQUIREMENT_ANALYZER = "requirement_analyzer"
    CLARIFICATION = "clarification"
    DISCOVERY = "discovery"
    LICENSE = "license"
    MERGE = "merge"
    CLEANING = "cleaning"
    CURATOR = "curator"
    TRANSLATION = "translation"
    QUALITY_EVALUATOR = "quality_evaluator"
    GENERATOR = "generator"
    CRITIC = "critic"
    VALIDATOR = "validator"
    BIAS = "bias"
    BENCHMARK = "benchmark"
    FORMATTER = "formatter"
    PACKAGING = "packaging"
    EXPLAINABILITY = "explainability"


#: Nodes that may be removed by a legal mutation.
OPTIONAL_NODES: frozenset[Node] = frozenset(
    {Node.CLARIFICATION, Node.TRANSLATION, Node.GENERATOR, Node.BIAS}
)

#: Mandatory validation can never be removed (frozen rule).
MANDATORY_NODES: frozenset[Node] = frozenset(
    {Node.VALIDATOR, Node.QUALITY_EVALUATOR, Node.PACKAGING}
)

#: Ordering constraints: (earlier, later). Graph Validator enforces these.
ORDERING_RULES: tuple[tuple[Node, Node], ...] = (
    (Node.DISCOVERY, Node.LICENSE),          # never use data before license check
    (Node.LICENSE, Node.MERGE),
    (Node.MERGE, Node.CLEANING),
    (Node.CLEANING, Node.CURATOR),
    (Node.CURATOR, Node.TRANSLATION),        # curate before translation to avoid wasted compute
    (Node.LICENSE, Node.CURATOR),
    (Node.CURATOR, Node.QUALITY_EVALUATOR),
    (Node.TRANSLATION, Node.QUALITY_EVALUATOR),
    (Node.GENERATOR, Node.CRITIC),           # generated data must face the Critic
    (Node.CRITIC, Node.VALIDATOR),
    (Node.VALIDATOR, Node.BENCHMARK),
    (Node.QUALITY_EVALUATOR, Node.FORMATTER),
    (Node.FORMATTER, Node.PACKAGING),
    (Node.PACKAGING, Node.EXPLAINABILITY),
)

#: If a node is present, its dependencies must also be present.
REQUIRED_COMPANIONS: dict[Node, frozenset[Node]] = {
    Node.GENERATOR: frozenset({Node.CRITIC, Node.VALIDATOR}),  # never ship unchecked synth data
    Node.DISCOVERY: frozenset({Node.LICENSE}),                 # never skip the license gate
    Node.MERGE: frozenset({Node.DISCOVERY, Node.LICENSE}),
    Node.CLEANING: frozenset({Node.LICENSE}),
    Node.TRANSLATION: frozenset({Node.CURATOR}),
    Node.BENCHMARK: frozenset({Node.VALIDATOR}),
}


@dataclass(frozen=True)
class Workflow:
    name: str
    description: str
    nodes: tuple[Node, ...]


WORKFLOW_LIBRARY: dict[str, Workflow] = {
    "search_curate_export": Workflow(
        name="search_curate_export",
        description="Existing data fully satisfies the requirement. No generation.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.CURATOR,
            Node.QUALITY_EVALUATOR,
            Node.VALIDATOR,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "search_fill_gap": Workflow(
        name="search_fill_gap",
        description="Partial match found; synthetic generation fills a justified gap.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.CURATOR,
            Node.QUALITY_EVALUATOR,
            Node.GENERATOR,
            Node.CRITIC,
            Node.VALIDATOR,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "dataset_search_only": Workflow(
        name="dataset_search_only",
        description="Discovery and licensing only; package candidate metadata without data processing.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.QUALITY_EVALUATOR,
            Node.VALIDATOR,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "clean_quality_export": Workflow(
        name="clean_quality_export",
        description="Search, license, merge, clean, score, validate, benchmark, and export without translation or generation.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.MERGE,
            Node.CLEANING,
            Node.CURATOR,
            Node.QUALITY_EVALUATOR,
            Node.CRITIC,
            Node.VALIDATOR,
            Node.BENCHMARK,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "multilingual_dataset": Workflow(
        name="multilingual_dataset",
        description="Search, license, merge, clean, curate, translate retained records, score, validate, benchmark, and export.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.CLARIFICATION,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.MERGE,
            Node.CLEANING,
            Node.CURATOR,
            Node.TRANSLATION,
            Node.QUALITY_EVALUATOR,
            Node.BIAS,
            Node.CRITIC,
            Node.VALIDATOR,
            Node.BENCHMARK,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "full_search_improve_export": Workflow(
        name="full_search_improve_export",
        description="Full platform workflow: search, license, merge, clean, curate, optional translate, score, critique, bias-check, validate, benchmark, format, package, explain.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.CLARIFICATION,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.MERGE,
            Node.CLEANING,
            Node.CURATOR,
            Node.TRANSLATION,
            Node.QUALITY_EVALUATOR,
            Node.CRITIC,
            Node.BIAS,
            Node.VALIDATOR,
            Node.BENCHMARK,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "full_search_improve_generate_export": Workflow(
        name="full_search_improve_generate_export",
        description="Full platform workflow with last-resort generation after search, licensing, merge, cleaning, translation, curation, and scoring.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.CLARIFICATION,
            Node.DISCOVERY,
            Node.LICENSE,
            Node.MERGE,
            Node.CLEANING,
            Node.CURATOR,
            Node.TRANSLATION,
            Node.QUALITY_EVALUATOR,
            Node.GENERATOR,
            Node.CRITIC,
            Node.BIAS,
            Node.VALIDATOR,
            Node.BENCHMARK,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
    "generate_only": Workflow(
        name="generate_only",
        description="Synthetic dataset generation only, used as a last-resort library workflow when explicitly requested.",
        nodes=(
            Node.REQUIREMENT_ANALYZER,
            Node.GENERATOR,
            Node.CRITIC,
            Node.VALIDATOR,
            Node.QUALITY_EVALUATOR,
            Node.BENCHMARK,
            Node.FORMATTER,
            Node.PACKAGING,
            Node.EXPLAINABILITY,
        ),
    ),
}


class Mutation(str, Enum):
    """The ONLY legal mutations the Planner may apply to a base workflow."""

    INSERT_AGENT = "insert_agent"
    REMOVE_OPTIONAL_AGENT = "remove_optional_agent"
    REPLACE_EQUIVALENT_AGENT = "replace_equivalent_agent"
    REORDER_SAFE_NODES = "reorder_safe_nodes"
