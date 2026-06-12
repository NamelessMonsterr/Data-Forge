"""Quality report implementation."""

from __future__ import annotations

from typing import Any

from reports.base import MarkdownReport


class QualityReport(MarkdownReport):
    """Render weighted quality score and hard-gate status."""

    filename = "quality_report.md"
    title = "Quality Report"

    def render(self, state: dict[str, Any]) -> str:
        """Return quality report Markdown."""
        quality = state.get("quality_report", {})
        gates = state.get("hard_gates", {})
        metrics = quality.get("metrics", {})
        lines = [
            "# Quality Report",
            "",
            f"Overall score: {quality.get('score', 0)}/100",
            f"Profile: {quality.get('profile', 'production')}",
            "",
            "## Hard Gates",
        ]
        lines.extend(f"- {name}: {value}" for name, value in gates.items())
        lines.append("")
        lines.append("## Weighted Metrics")
        lines.extend(f"- {name}: {value}" for name, value in metrics.items())
        return "\n".join(lines) + "\n"
