import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.llm_provider import (  # noqa: E402
    DeterministicProvider,
    HttpLLMProvider,
    LLMConfig,
    LLMError,
    LLMOrchestrator,
)


def ok_body(content="hello"):
    return json.dumps({"choices": [{"message": {"content": content}}]})


class ScriptedTransport:
    """Returns queued (status, body) tuples or raises queued exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def post(self, url, headers, body, timeout):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_provider(script, **kw):
    cfg = LLMConfig(live=True, base_url="https://x/v1", api_key="k", max_retries=2)
    return HttpLLMProvider(cfg, transport=ScriptedTransport(script), sleep=lambda s: None,
                           clock=kw.get("clock", lambda: 0.0))


class HttpProviderTest(unittest.TestCase):
    def test_success(self):
        p = make_provider([(200, ok_body("hi"))])
        r = p.generate("prompt")
        self.assertEqual(r.text, "hi")
        self.assertEqual(r.provider, "live-http")
        self.assertFalse(r.fallback_used)
        self.assertEqual(r.attempts, 1)

    def test_retries_on_500_then_succeeds(self):
        p = make_provider([(500, "err"), (200, ok_body("ok"))])
        r = p.generate("prompt")
        self.assertEqual(r.text, "ok")
        self.assertEqual(r.attempts, 2)

    def test_retries_on_429_then_succeeds(self):
        p = make_provider([(429, "slow"), (200, ok_body("ok"))])
        self.assertEqual(p.generate("p").attempts, 2)

    def test_no_retry_on_400(self):
        t = ScriptedTransport([(400, "bad"), (200, ok_body())])
        cfg = LLMConfig(live=True, base_url="https://x/v1", max_retries=2)
        p = HttpLLMProvider(cfg, transport=t, sleep=lambda s: None, clock=lambda: 0.0)
        with self.assertRaises(LLMError):
            p.generate("p")
        self.assertEqual(t.calls, 1)  # did not retry

    def test_transport_error_retried(self):
        p = make_provider([LLMError("boom"), (200, ok_body("recovered"))])
        self.assertEqual(p.generate("p").text, "recovered")

    def test_malformed_response_raises(self):
        p = make_provider([(200, "{not json")])
        with self.assertRaises(LLMError):
            p.generate("p")

    def test_cooldown_after_threshold(self):
        clock = [0.0]
        cfg = LLMConfig(live=True, base_url="https://x/v1", max_retries=0)
        t = ScriptedTransport([(500, "e"), (500, "e"), (500, "e"), (500, "e")])
        p = HttpLLMProvider(cfg, transport=t, sleep=lambda s: None,
                            clock=lambda: clock[0], failure_threshold=3, cooldown_seconds=30)
        for _ in range(3):
            with self.assertRaises(LLMError):
                p.generate("p")
        self.assertTrue(p.in_cooldown)
        with self.assertRaises(LLMError) as ctx:
            p.generate("p")
        self.assertIn("circuit open", str(ctx.exception))

    def test_success_resets_failure_counter(self):
        cfg = LLMConfig(live=True, base_url="https://x/v1", max_retries=0)
        t = ScriptedTransport([(500, "e"), (200, ok_body("ok"))])
        p = HttpLLMProvider(cfg, transport=t, sleep=lambda s: None, clock=lambda: 0.0,
                            failure_threshold=3)
        with self.assertRaises(LLMError):
            p.generate("p")
        p.generate("p")
        self.assertEqual(p._consecutive_failures, 0)


class DeterministicProviderTest(unittest.TestCase):
    def test_offline_provider(self):
        r = DeterministicProvider().generate("summarize this please")
        self.assertEqual(r.provider, "local-deterministic")
        self.assertIn("deterministic", r.text)


class OrchestratorTest(unittest.TestCase):
    def test_offline_config_uses_deterministic(self):
        orch = LLMOrchestrator(env={"DATAFORGE_LIVE_LLM": "false"})
        r = orch.generate("p")
        self.assertEqual(r.provider, "local-deterministic")
        self.assertFalse(r.fallback_used)

    def test_live_primary_failure_labels_fallback(self):
        cfg = LLMConfig(live=True, base_url="https://x/v1", max_retries=0)
        primary = HttpLLMProvider(cfg, transport=ScriptedTransport([(500, "e")]),
                                  sleep=lambda s: None, clock=lambda: 0.0)
        orch = LLMOrchestrator(config=cfg, primary=primary)
        r = orch.generate("p")
        self.assertTrue(r.fallback_used)
        self.assertEqual(r.provider, "local-deterministic")

    def test_config_from_env(self):
        cfg = LLMConfig.from_env({"DATAFORGE_LIVE_LLM": "true", "DATAFORGE_LLM_TIMEOUT": "5"})
        self.assertTrue(cfg.live)
        self.assertEqual(cfg.timeout, 5.0)
        self.assertEqual(cfg.model, "meta/llama-3.1-8b-instruct")


if __name__ == "__main__":
    unittest.main(verbosity=2)
