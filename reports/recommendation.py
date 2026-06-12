"""Recommendation report implementation."""

from __future__ import annotations

from typing import Any

from reports.base import MarkdownReport


class RecommendationReport(MarkdownReport):
    """Render next-step recommendations for the dataset owner."""

    filename = "recommendation_report.md"
    title = "Recommendation Report"

    def render(self, state: dict[str, Any]) -> str:
        """Return recommendation report Markdown."""
        quality = state.get("quality_report", {})
        recommendation = "Ready for hackathon demo export."
        if quality.get("requires_generation"):
            recommendation = "Review generated samples before production use."
        return f"# Recommendation Report\n\n{recommendation}\n"
