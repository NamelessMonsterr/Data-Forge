"""Bias report implementation."""

from __future__ import annotations

from typing import Any

from reports.base import MarkdownReport


class BiasReport(MarkdownReport):
    """Render lightweight distribution and toxicity findings."""

    filename = "bias_report.md"
    title = "Bias Report"

    def render(self, state: dict[str, Any]) -> str:
        """Return bias report Markdown."""
        dataset = state.get("curated_dataset", {})
        bias = state.get("bias_report", {})
        return (
            "# Bias Report\n\n"
            f"Records sampled: {len(dataset.get('rows', []))}\n"
            f"Critical toxicity: {bias.get('critical_toxicity', 'PASS')}\n"
            f"Distribution risk: {bias.get('distribution_risk', 'low')}\n"
            f"Languages: {', '.join(bias.get('languages', []))}\n"
        )
