"""AI skill definitions for dataset intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.llm_orchestrator import LLMOrchestrator, LLMRequest, LLMResponse


@dataclass(frozen=True)
class SkillResult:
    """Serializable AI skill result."""

    text: str
    provider: str
    fallback_used: bool
    attempts: tuple[dict[str, Any], ...]

    @classmethod
    def from_response(cls, response: LLMResponse) -> "SkillResult":
        return cls(
            text=response.text,
            provider=response.provider,
            fallback_used=response.fallback_used,
            attempts=response.attempts,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "fallback_used": self.fallback_used,
            "attempts": list(self.attempts),
        }


class DatasetSummarySkill:
    """Generate a natural-language dataset summary."""

    name = "dataset_summary"

    def run(
        self,
        dataset_metadata: dict[str, Any],
        orchestrator: LLMOrchestrator,
    ) -> SkillResult:
        """Request a dataset summary without choosing the provider."""
        response = orchestrator.run(
            LLMRequest(
                skill=self.name,
                prompt=(
                    "Summarize this dataset for a user deciding whether it fits "
                    "their ML or analytics task."
                ),
                context=dataset_metadata,
            )
        )
        return SkillResult.from_response(response)


class DatasetRecommendationSkill:
    """Explain why a dataset matches a user query."""

    name = "dataset_recommendation"

    def run(
        self,
        recommendation_context: dict[str, Any],
        orchestrator: LLMOrchestrator,
    ) -> SkillResult:
        """Request a dataset recommendation without provider-specific logic."""
        response = orchestrator.run(
            LLMRequest(
                skill=self.name,
                prompt="Explain why this dataset is or is not a good match for the query.",
                context=recommendation_context,
            )
        )
        return SkillResult.from_response(response)
