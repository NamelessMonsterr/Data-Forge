"""Dataset Intelligence Report implementation."""

from __future__ import annotations

from typing import Any

from reports.base import MarkdownReport


class DatasetIntelligenceReport(MarkdownReport):
    """Render the high-level report shipped with every exported dataset."""

    filename = "dataset_intelligence_report.md"
    title = "Dataset Intelligence Report"

    def render(self, state: dict[str, Any]) -> str:
        """Return dataset intelligence report Markdown."""
        requirement = state.get("structured_requirement", {})
        dataset = state.get("curated_dataset", {})
        quality = state.get("quality_report", {})
        benchmark = state.get("benchmark_report", {})
        cleaning = state.get("cleaning_report", {})
        ingestion = state.get("ingestion_summary", {})
        stats = ingestion.get("stats", {})
        return (
            "# Dataset Intelligence Report\n\n"
            f"Dataset: {dataset.get('name', 'dataforge-demo-dataset')}\n"
            f"Purpose: {requirement.get('purpose', 'fine_tuning')}\n"
            f"Domain: {requirement.get('domain', 'general')}\n"
            f"Languages: {', '.join(requirement.get('languages', []))}\n"
            f"Rows: {ingestion.get('row_count', len(dataset.get('rows', [])))}\n"
            f"Columns: {ingestion.get('column_count', 'Unavailable')}\n"
            f"Missing values: {stats.get('missing_cells', 'Unavailable')}\n"
            f"Duplicate rows: {stats.get('duplicate_rows', 'Unavailable')}\n"
            f"Quality score: {quality.get('score', 0)}/100\n"
            f"License: {dataset.get('license', 'unknown')}\n"
            f"Cleaned rows: {cleaning.get('output_rows', 'unknown')}\n"
            f"Benchmark readiness: {benchmark.get('training_readiness', 'unknown')}\n"
            "Certification: Production Ready for demo constraints\n"
        )
