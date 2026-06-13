import io
import json
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.observability import (  # noqa: E402
    MetricsRegistry,
    configure_logging,
    get_request_id,
    log_event,
    new_request_id,
    set_request_id,
)


class LoggingTest(unittest.TestCase):
    def test_new_request_id_is_unique(self):
        a = new_request_id()
        b = new_request_id()
        self.assertNotEqual(a, b)
        self.assertEqual(get_request_id(), b)

    def test_emits_json_with_request_id_and_fields(self):
        buf = io.StringIO()
        configure_logging(stream=buf)
        set_request_id("req-123")
        logger = logging.getLogger("dataforge.test")
        log_event(logger, logging.INFO, "processed", dataset="ds1", rows=10)
        line = buf.getvalue().strip().splitlines()[-1]
        payload = json.loads(line)
        self.assertEqual(payload["msg"], "processed")
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["dataset"], "ds1")
        self.assertEqual(payload["rows"], 10)

    def test_configure_logging_is_idempotent(self):
        configure_logging()
        configure_logging()
        root = logging.getLogger()
        df_handlers = [h for h in root.handlers if getattr(h, "_dataforge", False)]
        self.assertEqual(len(df_handlers), 1)


class MetricsTest(unittest.TestCase):
    def test_counter_increments(self):
        reg = MetricsRegistry()
        reg.incr("a"); reg.incr("a", 3)
        self.assertEqual(reg.counter("a"), 4)

    def test_empty_histogram_snapshot_is_zeroed(self):
        snap = MetricsRegistry().histogram("h").snapshot()
        self.assertEqual(snap["count"], 0)
        self.assertEqual(snap["p95"], 0.0)

    def test_histogram_snapshot(self):
        reg = MetricsRegistry()
        h = reg.histogram("lat")
        for v in range(1, 101):
            h.observe(v)
        snap = h.snapshot()
        self.assertEqual(snap["count"], 100)
        self.assertEqual(snap["min"], 1)
        self.assertEqual(snap["max"], 100)
        self.assertEqual(snap["p95"], 95)  # nearest-rank p95 of 1..100

    def test_timed_records_duration(self):
        clock = iter([10.0, 10.5])
        reg = MetricsRegistry()
        with reg.timed("op", clock=lambda: next(clock)):
            pass
        self.assertAlmostEqual(reg.histogram("op").snapshot()["sum"], 0.5, places=3)

    def test_track_provider_records_primary_and_fallback(self):
        reg = MetricsRegistry()
        reg.track_provider("live-http", fallback_used=False)
        reg.track_provider("local-deterministic", fallback_used=True)
        self.assertEqual(reg.counter("llm.primary"), 1)
        self.assertEqual(reg.counter("llm.fallback"), 1)
        self.assertEqual(reg.counter("llm.calls.live-http"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
