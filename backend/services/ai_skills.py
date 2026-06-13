"""AI skill definitions for dataset intelligence.

Skills are *provider-agnostic*. Each skill assembles an ``LLMRequest`` and lets
the ``LLMOrchestrator`` decide who answers it: a live provider (NVIDIA NIM /
OpenAI) when live mode is configured, or the deterministic offline provider by
default. A skill never branches on the provider, so the exact same call path is
exercised online and offline -- the only thing that changes is answer quality.

This module exposes:
  * ``Skill``            - base class (name + default prompt + token budget)
  * concrete skills      - summary, recommendation, gap analysis, schema
                           inference, dataset card, quality narrative, search
                           intent
  * ``SKILLS``           - name -> instance registry
  * ``AISkillService``   - one-stop facade used by services / agents / the API
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.llm_orchestrator import (
    LLMOrchestrator,
    LLMRequest,
    LLMResponse,
)


@dataclass(frozen=True)
class SkillResult:
    """Serializable AI skill result."""

    text: str
    provider: str
    fallback_used: bool
    attempts: tuple[dict[str, Any], ...]
    skill: str = "skill"

    @classmethod
    def from_response(
        cls, response: LLMResponse, *, skill: str = "skill"
    ) -> "SkillResult":
        return cls(
            text=response.text,
            provider=response.provider,
            fallback_used=response.fallback_used,
            attempts=response.attempts,
            skill=skill,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "text": self.text,
            "provider": self.provider,
            "fallback_used": self.fallback_used,
            "attempts": list(self.attempts),
        }


class Skill:
    """Base class for all AI skills.

    Subclasses set a stable ``name`` (used as the routing key by the
    orchestrator and the deterministic provider), a default instruction
    ``prompt``, and a ``max_tokens`` budget. ``run`` is provider-agnostic by
    construction.
    """

    name: str = "skill"
    prompt: str = "Complete the requested dataset intelligence task."
    max_tokens: int = 512

    def run(
        self,
        context: dict[str, Any],
        orchestrator: LLMOrchestrator,
        *,
        prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> SkillResult:
        """Run the skill without choosing or knowing the provider."""
        response = orchestrator.run(
            LLMRequest(
                skill=self.name,
                prompt=prompt or self.prompt,
                context=context,
                max_tokens=max_tokens or self.max_tokens,
            )
        )
        return SkillResult.from_response(response, skill=self.name)


class DatasetSummarySkill(Skill):
    """Generate a natural-language dataset summary."""

    name = "dataset_summary"
    prompt = (
        "Summarize this dataset for a user deciding whether it fits their ML "
        "or analytics task."
    )


class DatasetRecommendationSkill(Skill):
    """Explain why a dataset matches a user query."""

    name = "dataset_recommendation"
    prompt = "Explain why this dataset is or is not a good match for the query."


class DatasetGapAnalysisSkill(Skill):
    """Identify coverage gaps between a requirement and a dataset."""

    name = "dataset_gap_analysis"
    prompt = (
        "Identify coverage gaps between the requirement and the dataset, then "
        "recommend search-first remediation before any synthetic generation."
    )


class SchemaInferenceSkill(Skill):
    """Infer field roles and the most likely training task from a schema."""

    name = "schema_inference"
    prompt = (
        "Infer the role of each field and the most likely training task for "
        "this dataset schema."
    )


class DataCardSkill(Skill):
    """Produce a Hugging Face-style dataset card grounded in metadata."""

    name = "dataset_card"
    max_tokens = 900
    prompt = "Produce a concise dataset card grounded only in the supplied metadata."


class QualityNarrativeSkill(Skill):
    """Turn quality metrics into a decision-useful explanation."""

    name = "quality_narrative"
    prompt = (
        "Explain the quality evaluation in plain language, citing the weakest "
        "and strongest dimensions and whether the profile threshold is met."
    )


class SearchIntentSkill(Skill):
    """Expand a raw search query into normalized intent."""

    name = "search_intent"
    prompt = (
        "Expand the search query into normalized intent terms, a likely "
        "domain, and useful filters."
    )


SKILLS: dict[str, Skill] = {
    skill.name: skill
    for skill in (
        DatasetSummarySkill(),
        DatasetRecommendationSkill(),
        DatasetGapAnalysisSkill(),
        SchemaInferenceSkill(),
        DataCardSkill(),
        QualityNarrativeSkill(),
        SearchIntentSkill(),
    )
}


class AISkillService:
    """Facade exposing every registered skill through one orchestrator.

    Construct once and reuse; the orchestrator owns provider health/fallback
    state. All convenience methods return a :class:`SkillResult`.
    """

    def __init__(self, orchestrator: LLMOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or LLMOrchestrator()
        self.skills = SKILLS

    def available(self) -> list[str]:
        """Return the sorted list of registered skill names."""
        return sorted(self.skills)

    def run(
        self,
        skill_name: str,
        context: dict[str, Any],
        **kwargs: Any,
    ) -> SkillResult:
        """Run a skill by name. Raises ``ValueError`` for unknown skills."""
        try:
            skill = self.skills[skill_name]
        except KeyError as exc:
            raise ValueError(f"Unknown skill: {skill_name}") from exc
        return skill.run(context, self.orchestrator, **kwargs)

    # -- Convenience wrappers used by services / agents -------------------

    def summarize_dataset(self, metadata: dict[str, Any]) -> SkillResult:
        return self.run("dataset_summary", metadata)

    def recommend_dataset(self, context: dict[str, Any]) -> SkillResult:
        return self.run("dataset_recommendation", context)

    def analyze_gaps(self, context: dict[str, Any]) -> SkillResult:
        return self.run("dataset_gap_analysis", context)

    def infer_schema(self, context: dict[str, Any]) -> SkillResult:
        return self.run("schema_inference", context)

    def dataset_card(self, context: dict[str, Any]) -> SkillResult:
        return self.run("dataset_card", context)

    def quality_narrative(self, context: dict[str, Any]) -> SkillResult:
        return self.run("quality_narrative", context)

    def search_intent(self, query: str) -> SkillResult:
        return self.run("search_intent", {"query": query})
