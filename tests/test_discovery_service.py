"""Discovery architecture tests."""

from backend.services.discovery import (
    DatasetCandidate,
    DiscoveryQuery,
    DiscoveryService,
    LiveGitHubProvider,
    LiveHuggingFaceProvider,
    LiveWebSearchProvider,
    ProviderManager,
    WebSearchProvider,
)
from backend.services.license_policy import LicensePolicy


class FailingProvider:
    """Provider used to verify failure isolation."""

    name = "failing"

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Raise a provider error."""
        raise RuntimeError("provider unavailable")


class StaticProvider:
    """Provider used to verify provider-manager partial success."""

    name = "static"

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Return one candidate."""
        return [
            DatasetCandidate(
                id="static/healthcare",
                title="Healthcare Static Dataset",
                url="https://huggingface.co/datasets/static/healthcare",
                provider="huggingface",
                domain="huggingface.co",
                snippet="Healthcare English dataset.",
                metadata={"rows": 100, "coverage": 0.8, "tags": ["healthcare", "english"]},
                license_guess="apache-2.0",
                license_confidence=0.9,
            )
        ]


class FakeHttpClient:
    """Fake HTTP client for live provider tests."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        """Return configured payload and record call arguments."""
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.payload


def test_provider_manager_isolates_failures():
    """A failing provider should not block successful providers."""
    query = DiscoveryQuery(
        text="healthcare dataset",
        domain="healthcare",
        languages=("english",),
        target_model="nemotron",
    )
    manager = ProviderManager([FailingProvider(), StaticProvider()])

    candidates = manager.search(query)

    assert len(candidates) == 1
    assert manager.errors["failing"] == "provider unavailable"


def test_web_search_provider_outputs_metadata_only_candidates():
    """Web search should discover URLs without approving ingestion."""
    query = DiscoveryQuery(
        text="healthcare dataset",
        domain="healthcare",
        languages=("english",),
        target_model="nemotron",
    )

    candidates = WebSearchProvider(allowlisted_domains=("github.com",)).search(query)

    assert candidates[0].provider == "web"
    assert candidates[0].license_guess is None
    assert candidates[0].metadata["source_engine"] == "local-web-boundary"


def test_discovery_service_ranks_and_enriches_candidates():
    """Discovery service should return enriched, ranked candidate dictionaries."""
    service = DiscoveryService(provider_manager=ProviderManager([StaticProvider()]))

    candidates = service.search(
        {
            "raw_request": "healthcare dataset",
            "domain": "healthcare",
            "languages": ["english"],
            "target_model": "nemotron",
        }
    )

    assert candidates[0]["discovery_score"] > 0
    assert candidates[0]["metadata"]["trusted_domain"] is True
    assert candidates[0]["license_guess"] == "apache-2.0"


def test_license_policy_blocks_unknown_web_candidates():
    """Unknown web licenses should not pass the license hard gate."""
    candidates = [
        {
            "id": "web/example",
            "license_guess": None,
            "provider": "web",
            "url": "https://example.com/dataset",
        }
    ]

    compatible, decisions = LicensePolicy().evaluate(candidates)

    assert compatible == []
    assert decisions[0]["status"] == "UNKNOWN"


def test_live_huggingface_provider_normalizes_api_response():
    """Live Hugging Face provider should normalize API JSON without network in tests."""
    client = FakeHttpClient(
        [
            {
                "id": "org/healthcare-instructions",
                "description": "Healthcare instructions",
                "downloads": 100,
                "likes": 5,
                "lastModified": "2026-06-01",
                "tags": ["license:apache-2.0", "healthcare"],
                "cardData": {"size_categories": ["1k<n<10k"]},
            }
        ]
    )
    query = DiscoveryQuery(
        text="healthcare",
        domain="healthcare",
        languages=("english",),
        target_model="nemotron",
    )

    candidates = LiveHuggingFaceProvider(client).search(query)

    assert candidates[0].id == "hf/org/healthcare-instructions"
    assert candidates[0].license_guess == "apache-2.0"
    assert candidates[0].metadata["rows"] == 5000


def test_live_github_provider_normalizes_repository_response():
    """Live GitHub provider should normalize repository search JSON."""
    client = FakeHttpClient(
        {
            "items": [
                {
                    "full_name": "org/healthcare-dataset",
                    "html_url": "https://github.com/org/healthcare-dataset",
                    "description": "Healthcare dataset repo",
                    "stargazers_count": 42,
                    "updated_at": "2026-06-01",
                    "owner": {"login": "org"},
                    "license": {"spdx_id": "MIT"},
                }
            ]
        }
    )
    query = DiscoveryQuery(
        text="healthcare",
        domain="healthcare",
        languages=("english",),
        target_model="nemotron",
    )

    candidates = LiveGitHubProvider(client, token="token").search(query)

    assert candidates[0].id == "github/org/healthcare-dataset"
    assert candidates[0].license_guess == "mit"
    assert candidates[0].metadata["stars"] == 42
    assert client.calls[0]["headers"]["Authorization"] == "Bearer token"


def test_live_web_search_provider_normalizes_metadata_only_results():
    """Live web search should normalize metadata-only URL results."""
    client = FakeHttpClient(
        {
            "results": [
                {
                    "title": "Healthcare Data Portal",
                    "url": "https://data.gov/healthcare",
                    "snippet": "Dataset landing page",
                    "license_guess": None,
                }
            ]
        }
    )
    query = DiscoveryQuery(
        text="healthcare",
        domain="healthcare",
        languages=("english",),
        target_model="nemotron",
    )

    candidates = LiveWebSearchProvider("https://search.example/api", client).search(query)

    assert candidates[0].provider == "web"
    assert candidates[0].domain == "data.gov"
    assert candidates[0].metadata["source_engine"] == "configured-web-search"
