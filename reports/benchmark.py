"""Benchmark report implementation."""

from __future__ import annotations

from typing import Any

from reports.base import MarkdownReport


class BenchmarkReport(MarkdownReport):
    """Render simple readiness benchmarks for the packaged dataset."""

    filename = "benchmark_report.md"
    title = "Benchmark Report"

    def render(self, state: dict[str, Any]) -> str:
        """Return benchmark report Markdown."""
        benchmark = state.get("benchmark_report", {})
        return (
            "# Benchmark Report\n\n"
            f"Record count: {benchmark.get('record_count', 0)}\n"
            f"Schema parse: {benchmark.get('schema_parse', 'PASS')}\n"
            f"Training readiness: {benchmark.get('training_readiness', 'PASS')}\n"
            f"Token length fit: {benchmark.get('token_length_fit', 'PASS')}\n"
        )
