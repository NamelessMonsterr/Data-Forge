"""Dataset ingestion service tests."""

from pathlib import Path

import pytest

from backend.services.ingestion import DatasetIngestionService


def test_ingest_csv_normalizes_rows_and_writes_artifacts(tmp_path: Path):
    service = DatasetIngestionService(tmp_path)

    result = service.ingest(
        filename="patients.csv",
        content="name,age,condition\nAsha,32,diabetes\nRavi,,asthma\nAsha,32,diabetes\n",
    )
    body = result.to_dict()

    assert body["format"] == "csv"
    assert body["row_count"] == 3
    assert body["column_count"] == 3
    assert body["preview"][1]["age"] is None
    assert body["schema"]["age"]["missing_count"] == 1
    assert body["stats"]["duplicate_rows"] == 1
    assert Path(body["artifacts"]["normalized_dataset"]).exists()
    assert Path(body["artifacts"]["schema"]).exists()
    assert Path(body["artifacts"]["ingestion_report"]).exists()


def test_ingest_jsonl_infers_schema_and_preview(tmp_path: Path):
    service = DatasetIngestionService(tmp_path)

    result = service.ingest(
        filename="instructions.jsonl",
        content='{"instruction":"take medicine","label":true}\n{"instruction":"rest","label":false}\n',
    )
    body = result.to_dict()

    assert body["format"] == "jsonl"
    assert body["schema"]["label"]["type"] == "boolean"
    assert body["schema"]["instruction"]["type"] == "string"
    assert body["preview"][0]["instruction"] == "take medicine"


def test_ingest_rejects_unsupported_format(tmp_path: Path):
    service = DatasetIngestionService(tmp_path)

    with pytest.raises(ValueError, match="Unsupported dataset format"):
        service.ingest(filename="dataset.xlsx", content="not parsed yet")
