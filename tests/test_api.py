"""FastAPI endpoint tests for executable workflows."""

from fastapi.testclient import TestClient

from backend.app.main import app


def test_workflow_start_executes_vertical_slice():
    """The workflow endpoint should return execution messages and artifacts."""
    client = TestClient(app)

    response = client.post(
        "/workflow/start",
        json={"request": "I need a Hindi-English instruction dataset for healthcare."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["workflow"] == "multilingual_dataset"
    assert body["artifacts"]["dataset_zip"].endswith("dataset.zip")
    assert body["messages"][0]["agent"] == "requirement_analyzer"
    assert "benchmark" in [message["agent"] for message in body["messages"]]
    assert "planner_mutations" in body
    assert body["planner_confidence"] > 0
    assert body["planner_alternatives"]


def test_platform_catalog_endpoints_expose_workflows_and_router():
    """The API should expose workflow-library and router status surfaces."""
    client = TestClient(app)

    workflows = client.get("/workflows").json()
    router = client.get("/router/status").json()
    cards = client.get("/agents/cards").json()
    services = client.get("/services/manifests").json()

    assert "full_search_improve_export" in workflows["workflows"]
    assert "nim" in router["failover_chain"]
    assert router["selected_provider"] == "nim"
    assert "planner" in cards["cards"]
    assert cards["cards"]["planner"]["registry_agent"] is False
    assert len([card for card in cards["cards"].values() if card["registry_agent"]]) == 17
    assert services["services"]["report_service"]["registry_agent"] is False


def test_discovery_search_endpoint_returns_ranked_candidates():
    """Discovery API should expose ranked candidates without ingestion."""
    client = TestClient(app)

    response = client.post(
        "/discovery/search",
        json={"request": "I need an English-Hindi healthcare instruction dataset."},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["planning"]["confidence"] > 0
    assert body["candidates"]
    assert body["candidates"][0]["discovery_score"] >= body["candidates"][-1]["discovery_score"]
    assert "providers" in body["provider_status"]


def test_project_and_run_status_surfaces():
    """Projects and workflow runs should be queryable through platform APIs."""
    client = TestClient(app)

    project = client.post(
        "/projects",
        json={"name": "Healthcare Dataset", "quality_profile": "production"},
    ).json()
    workflow = client.post(
        "/workflow/start",
        json={
            "project_id": project["project_id"],
            "request": "I need a Hindi-English instruction dataset for healthcare.",
        },
    ).json()
    status = client.get(f"/workflow/status/{workflow['task_id']}").json()
    project_detail = client.get(f"/projects/{project['project_id']}").json()

    assert status["run"]["task_id"] == workflow["task_id"]
    assert status["run"]["project_id"] == project["project_id"]
    assert project_detail["project"]["name"] == "Healthcare Dataset"
    assert project_detail["runs"]
