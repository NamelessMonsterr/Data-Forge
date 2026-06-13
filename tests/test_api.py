"""FastAPI endpoint tests for executable workflows."""

import os
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient

import backend.app.main as app_main
from backend.app.main import app
from backend.vault import ProviderVault, SecretBox, VaultStore


def authenticated_client() -> TestClient:
    """Return a client with an HTTP-only auth session cookie."""
    return authenticated_client_with_email()[0]


def authenticated_client_with_email(email: str | None = None) -> tuple[TestClient, str]:
    """Return a logged-in client and its email."""
    os.environ["DATAFORGE_COOKIE_SECURE"] = "false"
    client = TestClient(app)
    email = email or f"test-{uuid4().hex}@example.com"
    password = "supersecret"
    register = client.post("/auth/register", json={"email": email, "password": password})
    assert register.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return client, email


def test_workflow_start_executes_vertical_slice():
    """The workflow endpoint should abort cleanly when live discovery is disabled."""
    client = authenticated_client()

    response = client.post(
        "/workflow/start",
        json={"request": "I need a Hindi-English instruction dataset for healthcare."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "aborted"
    assert body["workflow"] == "multilingual_dataset"
    assert body["artifacts"] == {}
    assert body["messages"][0]["agent"] == "requirement_analyzer"
    assert "license" in [message["agent"] for message in body["messages"]]
    assert "benchmark" not in [message["agent"] for message in body["messages"]]
    assert "planner_mutations" in body
    assert body["planner_confidence"] > 0
    assert body["planner_alternatives"]


def test_platform_catalog_endpoints_expose_workflows_and_router():
    """The API should expose workflow-library and router status surfaces."""
    client = TestClient(app)

    workflows = client.get("/workflows").json()
    router = client.get("/router/status").json()
    llm = client.get("/ai/llm/status").json()
    cards = client.get("/agents/cards").json()
    services = client.get("/services/manifests").json()

    assert "full_search_improve_export" in workflows["workflows"]
    assert "nim" in router["failover_chain"]
    assert router["selected_provider"] == "nim"
    assert llm["active_provider"] == "local-deterministic"
    assert llm["mode"] == "offline_deterministic"
    assert "planner" in cards["cards"]
    assert cards["cards"]["planner"]["registry_agent"] is False
    assert len([card for card in cards["cards"].values() if card["registry_agent"]]) == 17
    assert services["services"]["report_service"]["registry_agent"] is False


def test_local_frontend_origin_is_allowed_by_cors():
    """The static frontend dev server should be allowed to call the API."""
    client = TestClient(app)

    response = client.options(
        "/datasets/search",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_discovery_search_endpoint_returns_ranked_candidates():
    """Discovery API should be honest when live public discovery is disabled."""
    client = TestClient(app)

    response = client.post(
        "/discovery/search",
        json={"request": "I need an English-Hindi healthcare instruction dataset."},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["planning"]["confidence"] > 0
    assert body["candidates"] == []
    assert body["discovery"]["enabled"] is False
    assert "providers" in body["provider_status"]


def test_dataset_ingest_endpoint_returns_normalized_preview():
    """Dataset ingestion should parse real user content and expose demo-ready metadata."""
    client = TestClient(app)

    response = client.post(
        "/datasets/ingest",
        json={
            "filename": "healthcare.csv",
            "content": "instruction,language\nTake water,en\nPani piyo,hi\n",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["format"] == "csv"
    assert body["row_count"] == 2
    assert body["column_count"] == 2
    assert body["preview"][0]["instruction"] == "Take water"
    assert body["schema"]["language"]["type"] == "string"
    assert body["artifacts"]["normalized_dataset"].endswith("normalized_dataset.jsonl")


def test_dataset_ingest_endpoint_returns_400_for_invalid_upload():
    """Invalid uploads should return a friendly client error instead of a 500."""
    client = TestClient(app)

    response = client.post(
        "/datasets/ingest",
        json={"filename": "dataset.xlsx", "content": "not supported"},
    )

    assert response.status_code == 400
    assert "Unsupported dataset format" in response.json()["detail"]


def test_dataset_process_endpoint_generates_downloadable_artifacts():
    """Uploaded dataset processing should return a full package artifact surface."""
    client = authenticated_client()

    response = client.post(
        "/datasets/process",
        json={
            "filename": "healthcare.csv",
            "request": "Analyze this uploaded healthcare instruction dataset.",
            "content": "instruction,response,language\nTake water,Hydrate,en\nPani piyo,Hydrate,hi\n",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["workflow"] == "uploaded_dataset_package"
    assert body["summary"]["rows"] == 2
    assert body["summary"]["columns"] == 3
    assert body["artifacts"]["dataset_zip"].endswith("dataset.zip")
    assert body["artifacts"]["manifest"].endswith("manifest.json")
    assert body["catalog_record"]["source"] == "local_upload"
    assert body["checksums"]


def test_dataset_search_endpoint_handles_empty_local_results():
    """Local-only search should handle an empty or unmatched catalog cleanly."""
    client = authenticated_client()

    response = client.post(
        "/datasets/search",
        json={
            "query": "zzzz unmatched private dataset query",
            "include_public": False,
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["counts"]["public"] == 0
    assert "results" in body


def test_dataset_search_endpoint_finds_processed_uploads():
    """Dataset search should return uploaded catalog entries after processing."""
    client = authenticated_client()
    processed = client.post(
        "/datasets/process",
        json={
            "filename": "diabetes.csv",
            "request": "Analyze diabetes prediction data.",
            "content": "age,glucose,bmi,outcome\n42,145,31.2,1\n39,120,26.4,0\n",
        },
    ).json()

    catalog = client.get("/datasets/catalog").json()
    search = client.post(
        "/datasets/search",
        json={"query": "glucose bmi diabetes", "include_public": True},
    ).json()

    assert any(
        item["id"] == processed["catalog_record"]["id"]
        for item in catalog["datasets"]
    )
    assert search["counts"]["local"] >= 1
    assert search["counts"]["public"] == 0
    assert any(item["source"] == "local_upload" for item in search["results"])


def test_project_and_run_status_surfaces():
    """Projects and workflow runs should be queryable through platform APIs."""
    client = authenticated_client()

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
    assert workflow["status"] == "aborted"
    assert project_detail["project"]["name"] == "Healthcare Dataset"
    assert project_detail["runs"]


def test_artifact_endpoints_reject_invalid_task_ids():
    """Artifact paths should reject traversal-like task ids before path lookup."""
    client = authenticated_client()

    reports = client.get("/reports/bad..id")
    artifact = client.get("/artifacts/bad..id/dataset.zip")

    assert reports.status_code == 400
    assert artifact.status_code == 400


def test_saved_resource_routes_require_authentication():
    """User-owned project, workflow, catalog, and artifact routes require login."""
    client = TestClient(app)

    assert client.post("/datasets/process", json={"filename": "x.csv", "content": "a\n1\n"}).status_code == 401
    assert client.get("/datasets/catalog").status_code == 401
    assert client.post("/datasets/search", json={"query": "x"}).status_code == 401
    assert client.post("/projects", json={"name": "Private"}).status_code == 401
    assert client.post("/workflow/start", json={"request": "private"}).status_code == 401


def test_team_share_makes_dataset_and_run_visible_to_member():
    """Team shares widen resource visibility without changing ownership."""
    alice, _ = authenticated_client_with_email()
    bob, bob_email = authenticated_client_with_email()

    processed = alice.post(
        "/datasets/process",
        json={
            "filename": "shared_diabetes.csv",
            "request": "Analyze diabetes prediction data.",
            "content": "age,glucose,bmi,outcome\n42,145,31.2,1\n39,120,26.4,0\n",
        },
    ).json()
    dataset_id = processed["catalog_record"]["id"]
    task_id = processed["task_id"]

    assert bob.get("/datasets/catalog").json()["datasets"] == []

    team = alice.post("/teams", json={"name": "Clinical Research"}).json()
    member = alice.post(
        f"/teams/{team['id']}/members",
        json={"email": bob_email, "role": "member"},
    )
    assert member.status_code == 200

    ds_share = alice.post(
        f"/teams/{team['id']}/shares",
        json={
            "resource_type": "dataset",
            "resource_id": dataset_id,
            "permission": "view",
        },
    )
    run_share = alice.post(
        f"/teams/{team['id']}/shares",
        json={
            "resource_type": "run",
            "resource_id": task_id,
            "permission": "view",
        },
    )
    assert ds_share.status_code == 200
    assert run_share.status_code == 200

    shares = bob.get(f"/teams/{team['id']}/shares")
    assert shares.status_code == 200
    share_ids = {item["resource_id"] for item in shares.json()["shares"]}
    assert {dataset_id, task_id} <= share_ids

    catalog = bob.get("/datasets/catalog").json()
    assert any(item["id"] == dataset_id for item in catalog["datasets"])

    search = bob.post(
        "/datasets/search",
        json={"query": "glucose bmi diabetes", "include_public": False},
    ).json()
    assert any(item["id"] == dataset_id for item in search["results"])

    status = bob.get(f"/workflow/status/{task_id}")
    assert status.status_code == 200
    assert status.json()["run"]["task_id"] == task_id


def test_team_share_does_not_share_provider_vault_keys():
    """Provider keys remain strictly per-user even when resources are shared."""
    old_vault = app_main.provider_vault
    with tempfile.TemporaryDirectory() as tmp:
        app_main.provider_vault = ProviderVault(
            VaultStore(os.path.join(tmp, "vault.db")),
            SecretBox(b"api-test-vault-key-long-enough"),
        )
        try:
            alice, _ = authenticated_client_with_email()
            bob, bob_email = authenticated_client_with_email()

            saved = alice.post(
                "/settings/providers/nvidia",
                json={"api_key": "ALICE-NVIDIA-KEY"},
            )
            assert saved.status_code == 200
            assert "ALICE-NVIDIA-KEY" not in saved.text

            team = alice.post("/teams", json={"name": "No Shared Keys"}).json()
            alice.post(
                f"/teams/{team['id']}/members",
                json={"email": bob_email, "role": "member"},
            )

            providers = bob.get("/settings/providers").json()["providers"]
            nvidia = next(item for item in providers if item["provider"] == "nvidia")
            assert nvidia["configured"] is False
        finally:
            app_main.provider_vault = old_vault
