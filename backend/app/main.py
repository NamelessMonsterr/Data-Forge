"""DataForge AI - FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.core.agent_manifest import all_agent_manifests
from backend.core.execution import ExecutionEngine
from backend.core.repository import JsonRepository, RunRecord, utc_now
from backend.core.registry import AGENT_REGISTRY, capability_matrix
from backend.core.service_manifest import all_service_manifests
from backend.core.settings import get_settings
from backend.services.catalog import DatasetCatalogService, UnifiedDatasetSearchService
from backend.services.dataset_processing import DatasetProcessingService
from backend.services.discovery import DiscoveryService
from backend.services.ingestion import DatasetIngestionService
from backend.services.llm_orchestrator import LLMOrchestrator
from planner.planner import RuleBasedPlanner
from planner.workflow_library import WORKFLOW_LIBRARY
from router.hybrid_router import HybridRouter

app = FastAPI(
    title="DataForge AI",
    description="Autonomous AI Data Engineering Platform",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def repository() -> JsonRepository:
    """Create the configured repository boundary."""
    return JsonRepository(get_settings().storage.state_path)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "dataforge-ai"}


@app.get("/agents")
def list_agents() -> dict:
    """List registered agents (from the Agent Registry, single source of truth)."""
    return {
        "agents": {name: spec.summary() for name, spec in AGENT_REGISTRY.items()},
        "capability_matrix": capability_matrix(),
    }


@app.get("/agents/cards")
def list_agent_cards() -> dict:
    """Return machine-readable planner and agent capability cards."""
    return {"cards": all_agent_manifests(include_planner=True)}


@app.get("/services/manifests")
def list_service_manifests() -> dict:
    """Return machine-readable deterministic support service manifests."""
    return {"services": all_service_manifests()}


@app.get("/workflows")
def list_workflows() -> dict:
    """List frozen Workflow Library entries available to the Planner."""
    return {
        "workflows": {
            name: {
                "description": workflow.description,
                "nodes": [node.value for node in workflow.nodes],
            }
            for name, workflow in WORKFLOW_LIBRARY.items()
        }
    }


@app.post("/discovery/search")
def discovery_search(payload: dict) -> dict:
    """Search dataset providers and return ranked candidates without ingestion."""
    planner = RuleBasedPlanner()
    plan = planner.plan(payload)
    service = DiscoveryService()
    candidates = service.search(plan.structured_requirement)
    return {
        "structured_requirement": plan.structured_requirement,
        "planning": {
            "workflow": plan.workflow.name,
            "confidence": plan.confidence,
            "alternatives": list(plan.alternatives),
            "mutations": [mutation.to_dict() for mutation in plan.mutations],
        },
        "candidates": candidates,
        "provider_status": service.provider_status(),
    }


@app.get("/discovery/providers")
def discovery_providers() -> dict:
    """Return configured discovery providers and last error state."""
    service = DiscoveryService()
    return service.provider_status()


@app.post("/datasets/ingest")
def ingest_dataset(payload: dict) -> dict:
    """Parse a dataset payload and write normalized ingestion artifacts."""
    settings = get_settings()
    service = DatasetIngestionService(settings.storage.artifacts_root / "ingestions")
    try:
        result = service.ingest(
            filename=str(payload.get("filename", "dataset.csv")),
            content=str(payload.get("content", "")),
            source_format=payload.get("format"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()


@app.post("/datasets/process")
def process_dataset(payload: dict) -> dict:
    """Ingest uploaded dataset content and generate reports, manifest, and ZIP."""
    settings = get_settings()
    service = DatasetProcessingService(settings.storage.artifacts_root)
    try:
        result = service.process(
            filename=str(payload.get("filename", "dataset.csv")),
            content=str(payload.get("content", "")),
            source_format=payload.get("format"),
            request=str(payload.get("request", "Analyze uploaded dataset.")),
            quality_profile=str(payload.get("quality_profile", "production")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    catalog_record = DatasetCatalogService(repository()).index_processed_upload(result)
    result["catalog_record"] = {
        "id": catalog_record.dataset_id,
        "title": catalog_record.title,
        "source": catalog_record.source,
    }
    return result


@app.get("/datasets/catalog")
def list_dataset_catalog() -> dict:
    """List uploaded datasets indexed in the local catalog."""
    catalog = DatasetCatalogService(repository())
    return {"datasets": catalog.list_datasets()}


@app.post("/datasets/search")
def search_datasets(payload: dict) -> dict:
    """Search local uploaded datasets and optionally public dataset providers."""
    catalog = DatasetCatalogService(repository())
    service = UnifiedDatasetSearchService(catalog)
    return service.search(
        query=str(payload.get("query", "")),
        include_public=bool(payload.get("include_public", False)),
        limit=int(payload.get("limit", 10)),
    )


@app.post("/projects")
def create_project(payload: dict) -> dict:
    """Create a DataForge project."""
    repo = repository()
    project = repo.create_project(
        name=str(payload.get("name", "Untitled DataForge Project")),
        quality_profile=str(payload.get("quality_profile", "production")),
        target_model=str(payload.get("target_model", "nemotron")),
    )
    return project.__dict__


@app.get("/projects")
def list_projects() -> dict:
    """List DataForge projects."""
    repo = repository()
    return {"projects": [project.__dict__ for project in repo.list_projects()]}


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    """Return a DataForge project and its workflow runs."""
    repo = repository()
    project = repo.get_project(project_id)
    runs = repo.list_runs(project_id)
    return {
        "project": project.__dict__ if project else None,
        "runs": [run.__dict__ for run in runs],
    }


@app.post("/workflow/start")
def start_workflow(payload: dict) -> dict:
    """Plan, validate, execute, report, and package a dataset workflow."""
    planner = RuleBasedPlanner()
    plan = planner.plan(payload)
    if not plan.is_valid:
        return {
            "status": "invalid",
            "workflow": plan.workflow.name,
            "nodes": [node.value for node in plan.workflow.nodes],
            "validation_errors": list(plan.validation_errors),
            "request": payload,
        }

    settings = get_settings()
    engine = ExecutionEngine(artifacts_root=settings.storage.artifacts_root)
    execution = engine.execute(
        plan.workflow,
        payload,
        {
            "structured_requirement": plan.structured_requirement,
            "planner_rationale": plan.rationale,
        },
    )
    repo = repository()
    repo.save_run(
        RunRecord(
            task_id=execution.task_id,
            project_id=payload.get("project_id"),
            workflow=execution.workflow,
            status=execution.status,
            request=payload,
            artifacts=execution.artifacts,
            created_at=utc_now(),
            completed_at=utc_now(),
        )
    )
    return {
        "status": execution.status,
        "task_id": execution.task_id,
        "workflow": execution.workflow,
        "nodes": [node.value for node in plan.workflow.nodes],
        "validation_errors": [],
        "planner_rationale": plan.rationale,
        "planner_confidence": plan.confidence,
        "planner_alternatives": list(plan.alternatives),
        "planner_mutations": [mutation.to_dict() for mutation in plan.mutations],
        "messages": [message.model_dump(mode="json") for message in execution.messages],
        "artifacts": execution.artifacts,
        "progress": execution.progress.__dict__ if execution.progress else None,
        "request": payload,
    }


@app.get("/workflow/status/{task_id}")
def workflow_status(task_id: str) -> dict:
    """Return persisted workflow run status."""
    repo = repository()
    run = repo.get_run(task_id)
    return {"run": run.__dict__ if run else None}


@app.get("/workflow/runs")
def list_workflow_runs(project_id: str | None = None) -> dict:
    """List persisted workflow runs, optionally filtered by project."""
    repo = repository()
    return {"runs": [run.__dict__ for run in repo.list_runs(project_id)]}


@app.get("/router/status")
def router_status() -> dict:
    """Return provider routing policy and current in-memory provider stats."""
    router = HybridRouter()
    return router.status()


@app.get("/ai/llm/status")
def llm_status() -> dict:
    """Return LLM skill orchestrator provider priority and health."""
    return LLMOrchestrator().status()


@app.get("/reports/{task_id}")
def list_reports(task_id: str) -> dict:
    """List generated report files for an execution task."""
    reports_dir = get_settings().storage.artifacts_root / task_id / "reports"
    reports = []
    if reports_dir.exists():
        reports = [str(path) for path in sorted(reports_dir.glob("*.md"))]
    return {"task_id": task_id, "reports": reports}


@app.get("/artifacts/{task_id}/dataset.zip")
def download_dataset_zip(task_id: str) -> FileResponse:
    """Download a packaged dataset ZIP for an execution task."""
    zip_path = get_settings().storage.artifacts_root / task_id / "dataset.zip"
    return FileResponse(zip_path, filename="dataset.zip", media_type="application/zip")
