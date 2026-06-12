"""User-uploaded dataset processing pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.export import PackagingService
from backend.services.ingestion import DatasetIngestionService
from backend.services.quality import BenchmarkService, BiasService, QualityService


class DatasetProcessingService:
    """Turn an uploaded dataset into reports, manifest, checksums, and ZIP artifacts."""

    def __init__(self, artifacts_root: Path | str) -> None:
        self.artifacts_root = Path(artifacts_root)

    def process(
        self,
        *,
        filename: str,
        content: str,
        source_format: str | None = None,
        request: str = "Analyze uploaded dataset.",
        quality_profile: str = "production",
    ) -> dict[str, Any]:
        """Ingest uploaded content and package deterministic dataset artifacts."""
        task_id = f"upload-{uuid4().hex[:12]}"
        artifacts_dir = self.artifacts_root / task_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        ingestion = DatasetIngestionService(artifacts_dir / "ingestion").ingest(
            filename=filename,
            content=content,
            source_format=source_format,
        )
        rows = self._load_rows(Path(ingestion.artifacts["normalized_dataset"]))
        dataset = {
            "name": Path(filename).stem or "uploaded-dataset",
            "license": "user_provided",
            "rows": rows,
            "source_lineage": [filename],
        }
        structured_requirement = {
            "purpose": "uploaded_dataset_analysis",
            "domain": "uploaded",
            "languages": self._detect_languages(rows),
            "quality_profile": quality_profile,
            "request": request,
        }
        state = {
            "workflow": "uploaded_dataset_package",
            "structured_requirement": structured_requirement,
            "curated_dataset": dataset,
            "formatted_dataset": ingestion.artifacts["normalized_dataset"],
            "ingestion_summary": {
                "filename": filename,
                "format": ingestion.format,
                "row_count": ingestion.row_count,
                "column_count": ingestion.column_count,
                "schema": ingestion.schema,
                "stats": ingestion.stats,
                "artifacts": ingestion.artifacts,
            },
            "cleaning_report": {
                "input_rows": ingestion.row_count,
                "output_rows": ingestion.row_count,
                "duplicates_detected": ingestion.stats["duplicate_rows"],
                "missing_cells": ingestion.stats["missing_cells"],
            },
            "hard_gates": {
                "license": "USER_PROVIDED",
                "pii": "NOT_EVALUATED",
                "critical_toxicity": "NOT_EVALUATED",
            },
        }
        state["quality_report"] = QualityService().evaluate(dataset, profile=quality_profile)
        state["bias_report"] = BiasService().evaluate(dataset)
        state["benchmark_report"] = BenchmarkService().evaluate(dataset)
        state["validation_report"] = {
            "ready": bool(rows),
            "record_count": len(rows),
            "mode": "uploaded_dataset",
        }

        package = PackagingService().package(
            artifacts_dir,
            state,
            task_id=task_id,
            workflow="uploaded_dataset_package",
        )
        return {
            "status": "completed",
            "task_id": task_id,
            "workflow": "uploaded_dataset_package",
            "ingestion": ingestion.to_dict(),
            "summary": {
                "rows": ingestion.row_count,
                "columns": ingestion.column_count,
                "missing_values": ingestion.stats["missing_cells"],
                "duplicate_rows": ingestion.stats["duplicate_rows"],
                "checksum": ingestion.stats["source_sha256"],
                "schema": [
                    {"name": name, **metadata}
                    for name, metadata in ingestion.schema.items()
                ],
            },
            "quality_report": state["quality_report"],
            "artifacts": {
                "dataset_zip": str(package.zip_path),
                "manifest": str(package.manifest_path),
                "normalized_dataset": ingestion.artifacts["normalized_dataset"],
            },
            "checksums": package.checksums,
        }

    def _load_rows(self, dataset_path: Path) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in dataset_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _detect_languages(self, rows: list[dict[str, Any]]) -> list[str]:
        languages = sorted(
            {
                str(row.get("language")).strip()
                for row in rows
                if row.get("language") is not None and str(row.get("language")).strip()
            }
        )
        return languages or ["unknown"]
