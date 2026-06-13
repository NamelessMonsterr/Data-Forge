"""Discovery service tests for the production provider contract."""

from backend.services.discovery import DiscoveryService, HuggingFaceProvider
from backend.services.license_policy import LicensePolicy


class FakeHttpClient:
    """Fake HTTP client for provider contract tests."""

    def __init__(self, status=200, body="[]"):
        self.status = status
        self.body = body
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.status, self.body


def test_discovery_disabled_returns_empty_not_fabricated():
    """Offline discovery should be honest and never invent public datasets."""
    service = DiscoveryService(env={"DATAFORGE_DISCOVERY_LIVE": "false"})

    result = service.search("healthcare instruction dataset")

    assert result["enabled"] is False
    assert result["results"] == []
    assert "Discovery disabled" in result["note"]


def test_discovery_provider_status_reports_live_flag_and_providers():
    """Provider status should remain available for API surfaces."""
    service = DiscoveryService(env={"DATAFORGE_DISCOVERY_LIVE": "false"})

    status = service.provider_status()

    assert status["live"] is False
    assert "huggingface" in status["providers"]


def test_huggingface_provider_builds_clean_urls():
    """Provider URLs should be canonical HTTPS URLs without literal braces."""
    client = FakeHttpClient(
        body='[{"id":"org/healthcare-instructions","downloads":100,"tags":["healthcare"]}]'
    )

    refs = HuggingFaceProvider(client=client).search("healthcare")

    assert refs[0].url == "https://huggingface.co/datasets/org/healthcare-instructions"
    assert "{" not in refs[0].url
    assert "}" not in refs[0].url


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
