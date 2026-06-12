"""Hybrid router tests."""

from router.hybrid_router import HybridRouter, Provider, RouterRequest, RoutingPolicy


def test_router_records_successful_provider_call():
    """Router completion should update provider stats and decisions."""
    router = HybridRouter(chain=(Provider.NIM,))

    response = router.complete(RouterRequest(agent="planner", prompt="Plan workflow"))
    status = router.status()

    assert response.provider is Provider.NIM
    assert status["provider_stats"]["nim"]["success_count"] == 1
    assert status["decisions"]


def test_router_privacy_policy_prefers_ollama():
    """Privacy policy should prefer local Ollama when it is in the chain."""
    router = HybridRouter(chain=(Provider.NIM, Provider.OLLAMA), policy=RoutingPolicy.PRIVACY)

    assert router.select_provider() is Provider.OLLAMA
