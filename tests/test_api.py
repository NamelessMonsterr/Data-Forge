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
    llm = client.get("/ai/llm/status").json()
    cards = client.get("/agents/cards").json()
    services = client.get("/services/manifests").json()

    assert "full_search_improve_export" in workflows["workflows"]
    assert "nim" in router["failover_chain"]
    assert router["selected_provider"] == "nim"
    assert llm["provider_priority"][0] == "nim"
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
    client = TestClient(app)

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
    client = TestClient(app)

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
    client = TestClient(app)
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
    assert search["counts"]["public"] >= 1
    assert any(item["source"] == "local_upload" for item in search["results"])


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
