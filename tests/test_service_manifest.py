"""Service manifest tests."""

from backend.core.registry import AGENT_REGISTRY
from backend.core.service_manifest import all_service_manifests


def test_service_manifests_are_not_registry_agents():
    """Support service specs should stay separate from execution agents."""
    services = all_service_manifests()

    assert "report_service" in services
    assert "zip_service" in services
    assert "dataset_card_service" in services
    assert "manifest_service" in services
    assert "checksum_service" in services
    for service_id, manifest in services.items():
        assert service_id not in AGENT_REGISTRY
        assert manifest["type"] == "service"
        assert manifest["service_type"] in {"runtime", "platform"}
        assert manifest["registry_agent"] is False
        assert manifest["tools"]["required"]
        assert manifest["failure"]["returns"]


def test_service_manifests_classify_runtime_and_platform_services():
    """Service manifests should separate workflow runtime services from platform services."""
    services = all_service_manifests()

    assert services["zip_service"]["service_type"] == "runtime"
    assert services["report_service"]["service_type"] == "runtime"
    assert services["artifact_storage_service"]["service_type"] == "platform"
