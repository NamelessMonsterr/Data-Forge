import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.agents import AgentRegistry, CriticAgent, GeneratorAgent  # noqa: E402
from backend.services.llm_provider import LLMResult  # noqa: E402


class FakeOrchestrator:
    def __init__(self, text, provider="live-http", fallback_used=False):
        self._result = LLMResult(text, provider, fallback_used, attempts=1)
        self.prompts = []

    def generate(self, prompt, max_tokens=512):
        self.prompts.append(prompt)
        return self._result


class GeneratorAgentTest(unittest.TestCase):
    def test_parses_model_rows(self):
        body = '[{"instruction": "a", "response": "b"}, {"instruction": "c", "response": "d"}]'
        orch = FakeOrchestrator(body)
        result = GeneratorAgent(orch).run(["instruction", "response"], count=2)
        self.assertEqual(len(result.output["rows"]), 2)
        self.assertEqual(result.provider, "live-http")
        self.assertFalse(result.fallback_used)
        self.assertTrue(result.requires_llm)
        self.assertTrue(orch.prompts)

    def test_extracts_json_embedded_in_prose(self):
        body = 'Sure! Here you go:\n[{"q": "x", "a": "y"}]\nHope that helps.'
        result = GeneratorAgent(FakeOrchestrator(body)).run(["q", "a"], count=1)
        self.assertEqual(result.output["rows"][0], {"q": "x", "a": "y"})

    def test_malformed_output_falls_back_labeled(self):
        result = GeneratorAgent(FakeOrchestrator("sorry I cannot")).run(["instruction", "response"], count=3)
        self.assertEqual(len(result.output["rows"]), 3)
        self.assertTrue(result.fallback_used)
        self.assertIn("deterministic", result.output["rows"][0]["instruction"])

    def test_rows_missing_fields_are_rejected(self):
        body = '[{"instruction": "only one field"}]'
        result = GeneratorAgent(FakeOrchestrator(body)).run(["instruction", "response"], count=1)
        self.assertTrue(result.fallback_used)


class CriticAgentTest(unittest.TestCase):
    def test_parses_verdict(self):
        body = '{"verdict": "revise", "issues": ["too short"], "score": 55}'
        result = CriticAgent(FakeOrchestrator(body)).run([{"instruction": "a", "response": "b"}])
        self.assertEqual(result.output["verdict"], "revise")
        self.assertEqual(result.output["score"], 55)
        self.assertFalse(result.fallback_used)

    def test_invalid_verdict_falls_back(self):
        result = CriticAgent(FakeOrchestrator('{"verdict": "maybe"}')).run([{"instruction": "a", "response": ""}])
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.output["verdict"], "revise")

    def test_fallback_accepts_clean_rows(self):
        result = CriticAgent(FakeOrchestrator("garbage")).run([{"instruction": "a", "response": "b"}])
        self.assertEqual(result.output["verdict"], "accept")
        self.assertTrue(result.fallback_used)


class RegistryTest(unittest.TestCase):
    def test_registry_exposes_only_real_agents(self):
        reg = AgentRegistry(FakeOrchestrator("[]"))
        self.assertEqual(reg.names(), ["critic", "generator"])
        self.assertIsInstance(reg.get("generator"), GeneratorAgent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
