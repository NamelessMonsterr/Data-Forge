import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.health import HealthService, make_sqlite_check  # noqa: E402
from backend.app.pagination import TTLCache, paginate  # noqa: E402


class HealthTest(unittest.TestCase):
    def test_liveness_reports_uptime(self):
        ticks = iter([100.0, 105.0])
        svc = HealthService(clock=lambda: next(ticks))
        self.assertEqual(svc.liveness()["status"], "alive")

    def test_readiness_ok_when_all_checks_pass(self):
        svc = HealthService()
        svc.register("db", lambda: True)
        self.assertEqual(svc.readiness()["status"], "ready")

    def test_readiness_unready_when_check_fails(self):
        svc = HealthService()
        svc.register("db", lambda: False)
        self.assertEqual(svc.readiness()["status"], "unready")

    def test_readiness_handles_raising_check(self):
        svc = HealthService()
        def boom():
            raise RuntimeError("connection refused")
        svc.register("db", boom)
        out = svc.readiness()
        self.assertEqual(out["status"], "unready")
        self.assertIn("connection refused", out["checks"][0]["detail"])

    def test_sqlite_check_calls_repository(self):
        class FakeRepo:
            def __init__(self): self.called = False
            def list_datasets(self): self.called = True; return []
        repo = FakeRepo()
        self.assertTrue(make_sqlite_check(repo)())
        self.assertTrue(repo.called)


class PaginationTest(unittest.TestCase):
    def test_basic_paging(self):
        out = paginate(range(95), page=2, page_size=20)
        self.assertEqual(out["items"], list(range(20, 40)))
        self.assertEqual(out["total"], 95)
        self.assertEqual(out["total_pages"], 5)
        self.assertTrue(out["has_next"] and out["has_prev"])

    def test_page_clamped_to_bounds(self):
        out = paginate(range(10), page=99, page_size=20)
        self.assertEqual(out["page"], 1)
        self.assertFalse(out["has_next"])

    def test_page_size_clamped(self):
        self.assertEqual(paginate(range(500), page=1, page_size=10000)["page_size"], 200)

    def test_empty_collection(self):
        out = paginate([], page=1, page_size=20)
        self.assertEqual(out["items"], [])
        self.assertEqual(out["total_pages"], 1)


class TTLCacheTest(unittest.TestCase):
    def test_hit_and_miss(self):
        cache = TTLCache(ttl_seconds=10, clock=lambda: 1000.0)
        cache.set("k", "v")
        self.assertEqual(cache.get("k"), "v")
        self.assertIsNone(cache.get("missing"))

    def test_expiry(self):
        clock = [1000.0]
        cache = TTLCache(ttl_seconds=10, clock=lambda: clock[0])
        cache.set("k", "v")
        clock[0] += 11
        self.assertIsNone(cache.get("k"))

    def test_get_or_set_calls_producer_once(self):
        cache = TTLCache(ttl_seconds=10, clock=lambda: 0.0)
        calls = []
        def producer():
            calls.append(1)
            return "computed"
        self.assertEqual(cache.get_or_set("k", producer), "computed")
        self.assertEqual(cache.get_or_set("k", producer), "computed")
        self.assertEqual(len(calls), 1)

    def test_max_entries_evicts_oldest(self):
        clock = [0.0]
        cache = TTLCache(ttl_seconds=1000, max_entries=2, clock=lambda: clock[0])
        cache.set("a", 1); clock[0] += 1
        cache.set("b", 2); clock[0] += 1
        cache.set("c", 3)
        self.assertEqual(len(cache), 2)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("c"), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
