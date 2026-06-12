"""Uploaded dataset processing pipeline tests."""

from pathlib import Path
from zipfile import ZipFile

from backend.services.dataset_processing import DatasetProcessingService


def test_process_uploaded_dataset_generates_package(tmp_path: Path):
    service = DatasetProcessingService(tmp_path)

    result = service.process(
        filename="healthcare.csv",
        content="instruction,response,language\nDrink water,Stay hydrated,en\nRest,Sleep well,en\n",
        request="Analyze this uploaded healthcare dataset.",
    )

    zip_path = Path(result["artifacts"]["dataset_zip"])
    assert result["status"] == "completed"
    assert result["summary"]["rows"] == 2
    assert result["summary"]["columns"] == 3
    assert result["quality_report"]["score"] > 0
    assert zip_path.exists()
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        dataset_card = archive.read("dataset_card.md").decode("utf-8")
        intelligence_report = archive.read("reports/dataset_intelligence_report.md").decode("utf-8")

    assert "dataset.jsonl" in names
    assert "dataset_card.md" in names
    assert "dataset_card.json" in names
    assert "manifest.json" in names
    assert "reports/dataset_intelligence_report.md" in names
    assert "Rows: 2" in dataset_card
    assert "Rows: 2" in intelligence_report
