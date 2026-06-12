"""Dataset ingestion and normalization services."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


SUPPORTED_FORMATS = {"csv", "json", "jsonl"}


@dataclass(frozen=True)
class IngestionResult:
    """Serializable result returned after ingesting a source dataset."""

    ingestion_id: str
    filename: str
    format: str
    row_count: int
    column_count: int
    preview: list[dict[str, Any]]
    schema: dict[str, dict[str, Any]]
    stats: dict[str, Any]
    artifacts: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingestion_id": self.ingestion_id,
            "filename": self.filename,
            "format": self.format,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "preview": self.preview,
            "schema": self.schema,
            "stats": self.stats,
            "artifacts": self.artifacts,
        }


class DatasetIngestionService:
    """Parse user-provided datasets into DataForge's normalized JSONL contract."""

    def __init__(self, artifacts_root: Path | str) -> None:
        self.artifacts_root = Path(artifacts_root)

    def ingest(self, filename: str, content: str, source_format: str | None = None) -> IngestionResult:
        """Ingest a dataset payload and write normalized artifacts."""
        detected_format = self._detect_format(filename, source_format)
        if not content.strip():
            raise ValueError("Dataset content is empty.")

        rows = self._parse_rows(detected_format, content)
        if not rows:
            raise ValueError("Dataset did not contain any records.")

        normalized_rows = self._normalize_rows(rows)
        schema = self._infer_schema(normalized_rows)
        stats = self._build_stats(normalized_rows, schema, detected_format, content)

        ingestion_id = f"ing_{uuid4().hex[:12]}"
        artifact_dir = self.artifacts_root / ingestion_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        dataset_path = artifact_dir / "normalized_dataset.jsonl"
        schema_path = artifact_dir / "schema.json"
        report_path = artifact_dir / "ingestion_report.json"

        dataset_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=True, sort_keys=True) for row in normalized_rows)
            + "\n",
            encoding="utf-8",
        )
        schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
        report = {
            "filename": filename,
            "format": detected_format,
            "row_count": len(normalized_rows),
            "column_count": len(schema),
            "stats": stats,
        }
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

        return IngestionResult(
            ingestion_id=ingestion_id,
            filename=filename,
            format=detected_format,
            row_count=len(normalized_rows),
            column_count=len(schema),
            preview=normalized_rows[:5],
            schema=schema,
            stats=stats,
            artifacts={
                "normalized_dataset": str(dataset_path),
                "schema": str(schema_path),
                "ingestion_report": str(report_path),
            },
        )

    def _detect_format(self, filename: str, source_format: str | None) -> str:
        detected_format = (source_format or Path(filename).suffix.lstrip(".")).lower()
        if detected_format not in SUPPORTED_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_FORMATS))
            raise ValueError(f"Unsupported dataset format '{detected_format}'. Supported formats: {supported}.")
        return detected_format

    def _parse_rows(self, source_format: str, content: str) -> list[dict[str, Any]]:
        if source_format == "csv":
            return self._parse_csv(content)
        if source_format == "json":
            return self._parse_json(content)
        if source_format == "jsonl":
            return self._parse_jsonl(content)
        raise ValueError(f"Unsupported dataset format '{source_format}'.")

    def _parse_csv(self, content: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(content.splitlines())
        if not reader.fieldnames:
            raise ValueError("CSV content must include a header row.")
        return [dict(row) for row in reader]

    def _parse_json(self, content: str) -> list[dict[str, Any]]:
        payload = json.loads(content)
        if isinstance(payload, dict):
            for key in ("records", "data", "rows"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
            else:
                payload = [payload]
        if not isinstance(payload, list):
            raise ValueError("JSON dataset must be an object, a list of objects, or contain records/data/rows.")
        return self._ensure_object_rows(payload)

    def _parse_jsonl(self, content: str) -> list[dict[str, Any]]:
        rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        return self._ensure_object_rows(rows)

    def _ensure_object_rows(self, rows: list[Any]) -> list[dict[str, Any]]:
        object_rows = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"Record {index} is not a JSON object.")
            object_rows.append(dict(row))
        return object_rows

    def _normalize_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        columns = sorted({str(key) for row in rows for key in row.keys()})
        normalized = []
        for row in rows:
            normalized_row = {}
            for column in columns:
                normalized_row[column] = self._normalize_value(row.get(column))
            normalized.append(normalized_row)
        return normalized

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value

    def _infer_schema(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        schema = {}
        columns = rows[0].keys()
        for column in columns:
            values = [row[column] for row in rows]
            non_missing = [value for value in values if value is not None]
            inferred_types = {self._infer_type(value) for value in non_missing}
            if not inferred_types:
                data_type = "null"
            elif len(inferred_types) == 1:
                data_type = inferred_types.pop()
            elif inferred_types <= {"integer", "number"}:
                data_type = "number"
            else:
                data_type = "mixed"

            missing_count = len(values) - len(non_missing)
            schema[column] = {
                "type": data_type,
                "missing_count": missing_count,
                "missing_ratio": missing_count / len(values),
                "unique_count": len({json.dumps(value, sort_keys=True) for value in non_missing}),
            }
        return schema

    def _infer_type(self, value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, (dict, list)):
            return "object"
        return "string"

    def _build_stats(
        self,
        rows: list[dict[str, Any]],
        schema: dict[str, dict[str, Any]],
        source_format: str,
        content: str,
    ) -> dict[str, Any]:
        row_fingerprints = [json.dumps(row, sort_keys=True) for row in rows]
        duplicate_rows = len(row_fingerprints) - len(set(row_fingerprints))
        missing_cells = sum(column["missing_count"] for column in schema.values())
        total_cells = len(rows) * len(schema)
        return {
            "format": source_format,
            "duplicate_rows": duplicate_rows,
            "missing_cells": missing_cells,
            "missing_ratio": missing_cells / total_cells if total_cells else 0,
            "source_sha256": sha256(content.encode("utf-8")).hexdigest(),
        }
