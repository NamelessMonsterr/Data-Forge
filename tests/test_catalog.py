"""Dataset catalog search tests."""

from pathlib import Path

from backend.core.repository import JsonRepository
from backend.services.catalog import DatasetCatalogService, UnifiedDatasetSearchService
from backend.services.dataset_processing import DatasetProcessingService


def test_catalog_indexes_processed_upload_and_searches_by_schema(tmp_path: Path):
    repository = JsonRepository(tmp_path / "state.json")
    result = DatasetProcessingService(tmp_path / "artifacts").process(
        filename="diabetes.csv",
        content="age,glucose,bmi,outcome\n42,145,31.2,1\n39,120,26.4,0\n",
        request="Analyze diabetes prediction data.",
    )
    catalog = DatasetCatalogService(repository)

    record = catalog.index_processed_upload(result)
    matches = catalog.search("glucose bmi diabetes prediction")

    assert record.title == "diabetes"
    assert matches
    assert matches[0]["id"] == record.dataset_id
    assert matches[0]["rows"] == 2
    assert matches[0]["relevance_score"] > 0
    assert "semantic_relevance" in matches[0]
    assert matches[0]["ai_summary"]
    assert matches[0]["ai_provider"] == "local-deterministic"
    assert "glucose" in matches[0]["tags"]
    assert "recommended" in matches[0]["recommendation"]


def test_unified_search_returns_local_and_no_fabricated_public_results(tmp_path: Path):
    repository = JsonRepository(tmp_path / "state.json")
    result = DatasetProcessingService(tmp_path / "artifacts").process(
        filename="diabetes.csv",
        content="age,glucose,bmi,outcome\n42,145,31.2,1\n",
        request="Analyze diabetes prediction data.",
    )
    catalog = DatasetCatalogService(repository)
    catalog.index_processed_upload(result)

    search = UnifiedDatasetSearchService(catalog).search(
        "find diabetes datasets",
        include_public=True,
        limit=5,
    )

    assert search["counts"]["local"] >= 1
    assert search["counts"]["public"] == 0
    assert search["results"]
    assert {item["source"] for item in search["results"]} == {"local_upload"}


class FailingDiscovery:
    def search(self, query: str, intensity: str = "medium", limit: int | None = None):
        return {
            "enabled": True,
            "query": query,
            "intensity": intensity,
            "providers_used": ["huggingface", "data.gov"],
            "results": [],
            "errors": ["huggingface (healthcare): transport error: timed out"],
        }


class PartialDiscovery:
    def search(self, query: str, intensity: str = "medium", limit: int | None = None):
        return {
            "enabled": True,
            "query": query,
            "intensity": intensity,
            "providers_used": ["huggingface", "data.gov"],
            "results": [
                {
                    "id": "hf/example",
                    "title": "Healthcare Example",
                    "url": "https://huggingface.co/datasets/hf/example",
                    "source": "HuggingFace Hub",
                    "provider": "huggingface",
                    "description": "Healthcare patient demographics.",
                    "downloads": 120,
                    "tags": ["healthcare"],
                }
            ],
            "errors": ["data.gov (healthcare): data.gov returned status 503"],
        }


def test_unified_search_reports_provider_failure_status(tmp_path: Path):
    repository = JsonRepository(tmp_path / "state.json")
    catalog = DatasetCatalogService(repository)
    search = UnifiedDatasetSearchService(catalog, discovery=FailingDiscovery()).search(
        "healthcare",
        include_public=True,
    )

    assert search["search_status"] == "failed"
    assert search["warnings"] == ["huggingface (healthcare): transport error: timed out"]
    assert search["discovery"]["providers_used"] == ["huggingface", "data.gov"]
    assert search["counts"]["returned"] == 0


def test_unified_search_reports_partial_provider_status(tmp_path: Path):
    repository = JsonRepository(tmp_path / "state.json")
    catalog = DatasetCatalogService(repository)
    search = UnifiedDatasetSearchService(catalog, discovery=PartialDiscovery()).search(
        "healthcare",
        include_public=True,
    )

    assert search["search_status"] == "partial"
    assert search["warnings"] == ["data.gov (healthcare): data.gov returned status 503"]
    assert search["counts"]["public"] == 1
    assert search["results"][0]["source"] == "HuggingFace Hub"
