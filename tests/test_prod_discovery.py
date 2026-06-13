import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.discovery import (  # noqa: E402
    DataGovProvider,
    DiscoveryError,
    DiscoveryService,
    HuggingFaceProvider,
    KaggleProvider,
    resolve_intensity,
)


class FakeClient:
    def __init__(self, status=200, body=""):
        self.status = status
        self.body = body
        self.last_url = None

    def get(self, url, headers, timeout):
        self.last_url = url
        return self.status, self.body


class RecordingProvider:
    """Test double that records the limit it was asked to fetch."""

    name = "rec"
    source = "rec"

    def __init__(self):
        self.calls = []

    def search(self, query, limit=10):
        self.calls.append(limit)
        return []


HF_BODY = json.dumps([
    {"id": "squad", "downloads": 5000, "description": "QA dataset", "tags": ["qa"]},
    {"id": "glue", "downloads": 9000, "description": "benchmark"},
    {"modelId": "", "downloads": 1},
])

CKAN_BODY = json.dumps({
    "success": True,
    "result": {"results": [
        {"name": "crime-data", "title": "Crime Data", "notes": "n", "tags": [{"name": "safety"}]},
    ]},
})


class HuggingFaceTest(unittest.TestCase):
    def test_parses_and_builds_clean_urls(self):
        refs = HuggingFaceProvider(client=FakeClient(200, HF_BODY)).search("qa")
        self.assertEqual(len(refs), 2)
        squad = next(r for r in refs if r.id == "squad")
        self.assertEqual(squad.url, "https://huggingface.co/datasets/squad")
        for r in refs:
            self.assertTrue(r.url.startswith("https://"))
            self.assertNotIn("{", r.url)
            self.assertNotIn("}", r.url)

    def test_http_error_raises(self):
        with self.assertRaises(DiscoveryError):
            HuggingFaceProvider(client=FakeClient(503, "down")).search("x")

    def test_malformed_json_raises(self):
        with self.assertRaises(DiscoveryError):
            HuggingFaceProvider(client=FakeClient(200, "{not json")).search("x")

    def test_query_is_encoded_in_request_url(self):
        client = FakeClient(200, "[]")
        HuggingFaceProvider(client=client).search("name entity")
        self.assertIn("search=name+entity", client.last_url)


class DataGovTest(unittest.TestCase):
    def test_parses_ckan(self):
        refs = DataGovProvider(client=FakeClient(200, CKAN_BODY)).search("crime")
        self.assertEqual(refs[0].url, "https://catalog.data.gov/dataset/crime-data")
        self.assertEqual(refs[0].tags, ["safety"])

    def test_unsuccessful_response_raises(self):
        with self.assertRaises(DiscoveryError):
            DataGovProvider(client=FakeClient(200, json.dumps({"success": False}))).search("x")


class KaggleTest(unittest.TestCase):
    def test_unconfigured_returns_empty(self):
        provider = KaggleProvider(client=FakeClient(200, "[]"), env={})
        self.assertFalse(provider.configured)
        self.assertEqual(provider.search("x"), [])

    def test_configured_parses(self):
        body = json.dumps([{"ref": "u/ds", "title": "DS", "downloadCount": 3}])
        provider = KaggleProvider(client=FakeClient(200, body),
                                  env={"KAGGLE_USERNAME": "u", "KAGGLE_KEY": "k"})
        self.assertEqual(provider.search("x")[0].url, "https://www.kaggle.com/datasets/u/ds")


class DiscoveryServiceTest(unittest.TestCase):
    def test_disabled_returns_empty_not_fabricated(self):
        svc = DiscoveryService(providers=[HuggingFaceProvider(client=FakeClient(200, HF_BODY))], env={})
        out = svc.search("qa")
        self.assertFalse(out["enabled"])
        self.assertEqual(out["results"], [])
        self.assertIn("disabled", out["note"].lower())

    def test_enabled_aggregates_dedups_and_sorts(self):
        hf = HuggingFaceProvider(client=FakeClient(200, HF_BODY))
        gov = DataGovProvider(client=FakeClient(200, CKAN_BODY))
        svc = DiscoveryService(providers=[hf, gov], env={"DATAFORGE_DISCOVERY_LIVE": "true"})
        out = svc.search("data")
        self.assertTrue(out["enabled"])
        self.assertEqual(len(out["results"]), 3)
        self.assertEqual(out["results"][0]["id"], "glue")
        self.assertEqual(out["errors"], [])

    def test_one_provider_failure_is_isolated(self):
        good = HuggingFaceProvider(client=FakeClient(200, HF_BODY))
        bad = DataGovProvider(client=FakeClient(500, "err"))
        svc = DiscoveryService(providers=[good, bad], env={"DATAFORGE_DISCOVERY_LIVE": "true"})
        out = svc.search("x")
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(len(out["errors"]), 1)


class IntensityTest(unittest.TestCase):
    def _live_service(self, n_providers):
        provs = [HuggingFaceProvider(client=FakeClient(200, HF_BODY)) for _ in range(n_providers)]
        return DiscoveryService(providers=provs, env={"DATAFORGE_DISCOVERY_LIVE": "true"})

    def test_resolve_normalizes_and_defaults(self):
        self.assertEqual(resolve_intensity("bogus"), "medium")
        self.assertEqual(resolve_intensity(None), "medium")
        self.assertEqual(resolve_intensity(""), "medium")
        self.assertEqual(resolve_intensity("Very Hard"), "very_hard")
        self.assertEqual(resolve_intensity("very-hard"), "very_hard")
        self.assertEqual(resolve_intensity("INTENSE"), "intense")

    def test_easy_consults_one_provider_small_limit(self):
        out = self._live_service(3).search("x", intensity="easy")
        self.assertEqual(out["intensity"], "easy")
        self.assertEqual(out["intensity_label"], "Easy")
        self.assertEqual(len(out["providers_used"]), 1)
        self.assertEqual(out["limit_per_provider"], 5)

    def test_intense_consults_all_providers_large_limit(self):
        out = self._live_service(3).search("x", intensity="intense")
        self.assertEqual(len(out["providers_used"]), 3)
        self.assertEqual(out["limit_per_provider"], 100)

    def test_explicit_limit_overrides_profile(self):
        out = self._live_service(2).search("x", intensity="hard", limit=7)
        self.assertEqual(out["limit_per_provider"], 7)

    def test_profile_limit_is_passed_to_provider(self):
        rec = RecordingProvider()
        svc = DiscoveryService(providers=[rec, rec, rec], env={"DATAFORGE_DISCOVERY_LIVE": "true"})
        svc.search("x", intensity="medium")
        self.assertEqual(rec.calls[0], 12)

    def test_unknown_intensity_falls_back_to_medium(self):
        out = self._live_service(3).search("x", intensity="turbo")
        self.assertEqual(out["intensity"], "medium")
        self.assertEqual(len(out["providers_used"]), 2)

    def test_disabled_still_reports_intensity(self):
        svc = DiscoveryService(providers=[HuggingFaceProvider(client=FakeClient(200, HF_BODY))], env={})
        out = svc.search("x", intensity="hard")
        self.assertFalse(out["enabled"])
        self.assertEqual(out["intensity"], "hard")


if __name__ == "__main__":
    unittest.main(verbosity=2)
