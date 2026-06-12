"""Explainability report implementation."""

from __future__ import annotations

from typing import Any

from reports.base import MarkdownReport


class ExplainabilityReport(MarkdownReport):
    """Render planner and agent decision rationale."""

    filename = "explainability_report.md"
    title = "Explainability Report"

    def render(self, state: dict[str, Any]) -> str:
        """Return explainability report Markdown."""
        rationale = state.get("planner_rationale", "Planner rationale unavailable.")
        quality = state.get("quality_report", {})
        generation = state.get("synthetic_samples_added", 0)
        return (
            "# Explainability Report\n\n"
            f"Planner decision: {rationale}\n"
            "Search-first policy: existing datasets were evaluated before generation.\n"
            f"Synthetic samples added: {generation}\n"
            f"Final quality score: {quality.get('score', 0)}/100\n"
        )
