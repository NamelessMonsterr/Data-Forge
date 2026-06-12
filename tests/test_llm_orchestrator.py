"""LLM orchestrator and AI skill tests."""

import pytest

from backend.services.ai_skills import DatasetSummarySkill
from backend.services.llm_orchestrator import (
    LLMOrchestrator,
    LLMRequest,
    OpenAICompatibleProvider,
)
from backend.services.semantic_search import SemanticTextEncoder


class FailingProvider:
    name = "nim"

    def execute(self, request: LLMRequest) -> str:
        raise TimeoutError("provider timeout")


class PassingProvider:
    name = "gemini"

    def execute(self, request: LLMRequest) -> str:
        return f"ok:{request.skill}"


def test_llm_orchestrator_retries_and_falls_back():
    orchestrator = LLMOrchestrator(
        providers=[FailingProvider(), PassingProvider()],
        max_retries=2,
        cooldown_seconds=60,
    )

    response = orchestrator.run(
        LLMRequest(skill="dataset_summary", prompt="summarize", context={})
    )

    assert response.provider == "gemini"
    assert response.fallback_used is True
    assert [attempt["status"] for attempt in response.attempts] == [
        "failed",
        "failed",
        "success",
    ]
    assert orchestrator.status()["health"]["nim"]["available"] is False


def test_llm_orchestrator_raises_when_all_providers_fail():
    orchestrator = LLMOrchestrator(
        providers=[FailingProvider()],
        max_retries=1,
        cooldown_seconds=60,
    )

    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        orchestrator.run(LLMRequest(skill="dataset_summary", prompt="summarize"))


def test_dataset_summary_skill_uses_orchestrator_provider():
    orchestrator = LLMOrchestrator(providers=[PassingProvider()])

    result = DatasetSummarySkill().run(
        {"title": "diabetes", "rows": 2, "columns": 4},
        orchestrator,
    )

    assert result.provider == "gemini"
    assert result.text == "ok:dataset_summary"


def test_semantic_encoder_matches_related_dataset_terms():
    encoder = SemanticTextEncoder()

    similarity = encoder.similarity(
        "traffic accidents in bangalore",
        "road crash and vehicle collision reports",
    )

    assert similarity > 0


def test_default_orchestrator_uses_nvidia_provider_when_key_is_configured(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("NVIDIA_NIM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("NVIDIA_NIM_MODEL", "nvidia-test-model")
    monkeypatch.setenv("DATAFORGE_LLM_PROVIDERS", "nim,openai")

    orchestrator = LLMOrchestrator()

    assert isinstance(orchestrator.providers[0], OpenAICompatibleProvider)
    assert orchestrator.providers[0].name == "nim"
    assert orchestrator.providers[0].base_url == "https://example.test/v1"
    assert orchestrator.providers[0].model == "nvidia-test-model"
