"""Agent Registry - single source of truth for agent capabilities.

The Capability Matrix is DERIVED from this registry (documentation/UI only).
Never maintain the matrix separately - zero drift risk by construction.

The Planner consults the registry to allocate work and spawn only required agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Capability(str, Enum):
    """Capabilities advertised by registry-backed agents."""

    SEARCH = "search"
    LICENSE_CHECK = "license_check"
    MERGE = "merge"
    CLEAN = "clean"
    DEDUPLICATE = "deduplicate"
    PII_REMOVAL = "pii_removal"
    TRANSLATE = "translate"
    QUALITY_SCORE = "quality_score"
    GENERATE = "generate"
    CRITIQUE = "critique"
    VALIDATE = "validate"
    BIAS_ANALYSIS = "bias_analysis"
    BENCHMARK = "benchmark"
    FORMAT = "format"
    PACKAGE = "package"
    AUDIT = "audit"
    ANALYZE_REQUIREMENTS = "analyze_requirements"
    CLARIFY = "clarify"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    capabilities: tuple[Capability, ...]
    requires_llm: bool
    preferred_provider: str  # "nim" preferred; router handles failover
    input_type: str
    output_type: str
    emits_confidence: bool = True  # all agents speak the Confidence Protocol
    optional: bool = False  # optional agents may be removed by legal mutation
    category: str = "execution"
    requires: frozenset[str] = frozenset()
    produces: frozenset[str] = frozenset()
    estimated_cost: int = 1
    estimated_runtime_seconds: int = 5

    def summary(self) -> dict:
        return {
            "capabilities": [c.value for c in self.capabilities],
            "requires_llm": self.requires_llm,
            "preferred_provider": self.preferred_provider,
            "input": self.input_type,
            "output": self.output_type,
            "optional": self.optional,
            "category": self.category,
            "requires": sorted(self.requires),
            "produces": sorted(self.produces),
            "estimated_cost": self.estimated_cost,
            "estimated_runtime_seconds": self.estimated_runtime_seconds,
        }


AGENT_REGISTRY: dict[str, AgentSpec] = {
    "requirement_analyzer": AgentSpec(
        name="requirement_analyzer",
        capabilities=(Capability.ANALYZE_REQUIREMENTS,),
        requires_llm=True,
        preferred_provider="nim",
        input_type="natural_language_request",
        output_type="structured_requirement",
        category="orchestration_input",
        produces=frozenset({"structured_requirement"}),
        estimated_cost=2,
        estimated_runtime_seconds=4,
    ),
    "clarification": AgentSpec(
        name="clarification",
        capabilities=(Capability.CLARIFY,),
        requires_llm=True,
        preferred_provider="nim",
        input_type="structured_requirement",
        output_type="clarification_questions",
        optional=True,
        category="orchestration_input",
        requires=frozenset({"requirement_analyzer"}),
        produces=frozenset({"clarification_questions"}),
        estimated_cost=2,
        estimated_runtime_seconds=4,
    ),
    "discovery": AgentSpec(
        name="discovery",
        capabilities=(Capability.SEARCH,),
        requires_llm=False,
        preferred_provider="none",
        input_type="structured_requirement",
        output_type="candidate_datasets",
        category="discovery",
        requires=frozenset({"requirement_analyzer"}),
        produces=frozenset({"candidate_datasets"}),
        estimated_cost=2,
        estimated_runtime_seconds=10,
    ),
    "license": AgentSpec(
        name="license",
        capabilities=(Capability.LICENSE_CHECK,),
        requires_llm=False,
        preferred_provider="none",
        input_type="candidate_datasets",
        output_type="license_verdicts",
        category="governance",
        requires=frozenset({"discovery"}),
        produces=frozenset({"compatible_datasets", "license_decisions"}),
        estimated_cost=1,
        estimated_runtime_seconds=3,
    ),
    "merge": AgentSpec(
        name="merge",
        capabilities=(Capability.MERGE,),
        requires_llm=False,
        preferred_provider="none",
        input_type="compatible_datasets",
        output_type="merged_dataset",
        category="processing",
        requires=frozenset({"license"}),
        produces=frozenset({"merged_dataset"}),
        estimated_cost=2,
        estimated_runtime_seconds=15,
    ),
    "cleaning": AgentSpec(
        name="cleaning",
        capabilities=(Capability.CLEAN, Capability.DEDUPLICATE, Capability.PII_REMOVAL),
        requires_llm=False,
        preferred_provider="none",
        input_type="merged_dataset",
        output_type="clean_dataset",
        category="processing",
        requires=frozenset({"merge"}),
        produces=frozenset({"clean_dataset", "cleaning_report"}),
        estimated_cost=3,
        estimated_runtime_seconds=25,
    ),
    "curator": AgentSpec(
        name="curator",
        capabilities=(Capability.CLEAN, Capability.DEDUPLICATE, Capability.PII_REMOVAL),
        requires_llm=False,
        preferred_provider="none",
        input_type="dataset",
        output_type="curated_dataset",
        category="processing",
        requires=frozenset({"cleaning"}),
        produces=frozenset({"curated_dataset", "curation_stats"}),
        estimated_cost=3,
        estimated_runtime_seconds=30,
    ),
    "translation": AgentSpec(
        name="translation",
        capabilities=(Capability.TRANSLATE,),
        requires_llm=True,
        preferred_provider="nim",
        input_type="clean_dataset",
        output_type="translated_dataset",
        optional=True,
        category="processing",
        requires=frozenset({"curator"}),
        produces=frozenset({"translated_dataset"}),
        estimated_cost=5,
        estimated_runtime_seconds=45,
    ),
    "quality_evaluator": AgentSpec(
        name="quality_evaluator",
        capabilities=(Capability.QUALITY_SCORE,),
        requires_llm=True,  # LLM-judged metrics are sampled; heuristics are free
        preferred_provider="nim",
        input_type="curated_dataset",
        output_type="quality_report",
        category="evaluation",
        requires=frozenset({"curator"}),
        produces=frozenset({"quality_report"}),
        estimated_cost=3,
        estimated_runtime_seconds=20,
    ),
    "generator": AgentSpec(
        name="generator",
        capabilities=(Capability.GENERATE,),
        requires_llm=True,
        preferred_provider="nim",
        input_type="gap_specification",
        output_type="synthetic_samples",
        optional=True,  # generation is the LAST RESORT
        category="generation",
        requires=frozenset({"quality_evaluator"}),
        produces=frozenset({"synthetic_samples_added", "curated_dataset"}),
        estimated_cost=6,
        estimated_runtime_seconds=60,
    ),
    "critic": AgentSpec(
        name="critic",
        capabilities=(Capability.CRITIQUE,),
        requires_llm=True,
        preferred_provider="nim",
        input_type="synthetic_samples",
        output_type="critique_report",
        category="evaluation",
        requires=frozenset({"quality_evaluator"}),
        produces=frozenset({"critique_report"}),
        estimated_cost=3,
        estimated_runtime_seconds=18,
    ),
    "validator": AgentSpec(
        name="validator",
        capabilities=(Capability.VALIDATE,),
        requires_llm=True,
        preferred_provider="nim",
        input_type="dataset",
        output_type="validation_report",
        category="evaluation",
        requires=frozenset({"quality_evaluator", "critic"}),
        produces=frozenset({"validation_report"}),
        estimated_cost=3,
        estimated_runtime_seconds=15,
    ),
    "bias": AgentSpec(
        name="bias",
        capabilities=(Capability.BIAS_ANALYSIS,),
        requires_llm=False,  # MVP: lightweight distribution stats + toxicity pass
        preferred_provider="none",
        input_type="dataset",
        output_type="bias_report",
        optional=True,
        category="evaluation",
        requires=frozenset({"curator"}),
        produces=frozenset({"bias_report"}),
        estimated_cost=2,
        estimated_runtime_seconds=18,
    ),
    "benchmark": AgentSpec(
        name="benchmark",
        capabilities=(Capability.BENCHMARK,),
        requires_llm=False,
        preferred_provider="none",
        input_type="validated_dataset",
        output_type="benchmark_report",
        category="evaluation",
        requires=frozenset({"validator"}),
        produces=frozenset({"benchmark_report"}),
        estimated_cost=2,
        estimated_runtime_seconds=20,
    ),
    "formatter": AgentSpec(
        name="formatter",
        capabilities=(Capability.FORMAT,),
        requires_llm=False,
        preferred_provider="none",
        input_type="dataset",
        output_type="formatted_dataset",
        category="export",
        requires=frozenset({"validator"}),
        produces=frozenset({"formatted_dataset"}),
        estimated_cost=1,
        estimated_runtime_seconds=5,
    ),
    "packaging": AgentSpec(
        name="packaging",
        capabilities=(Capability.PACKAGE,),
        requires_llm=False,
        preferred_provider="none",
        input_type="formatted_dataset_and_reports",
        output_type="dataset_zip",
        category="export",
        requires=frozenset({"formatter"}),
        produces=frozenset({"dataset_zip", "dataset_card", "reports"}),
        estimated_cost=1,
        estimated_runtime_seconds=5,
    ),
    "explainability": AgentSpec(
        name="explainability",
        capabilities=(Capability.AUDIT,),
        requires_llm=True,  # turns the decision trail into a human-readable report
        preferred_provider="nim",
        input_type="decision_trail",
        output_type="explainability_report",
        category="audit",
        requires=frozenset({"packaging"}),
        produces=frozenset({"explainability_report"}),
        estimated_cost=2,
        estimated_runtime_seconds=10,
    ),
}


def capability_matrix() -> dict[str, list[str]]:
    """DERIVED view of the registry. Documentation only - never edited by hand."""
    return {
        name: [c.value for c in spec.capabilities]
        for name, spec in AGENT_REGISTRY.items()
    }
