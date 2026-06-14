"""DataForge AI - FastAPI application entrypoint."""

import os
from pathlib import Path
import re

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.app.health import HealthService, make_sqlite_check
from backend.app.observability import configure_logging
from backend.app.security import SecurityConfig, build_security_middleware
from backend.auth import AuthService, AuthStore, PermissionDenied
from backend.auth.access import assert_can, visible_records
from backend.auth.teams import (
    InsufficientTeamRole,
    NotATeamMember,
    TeamNotFound,
    TeamService,
    TeamStore,
)
from backend.auth.web import SESSION_COOKIE, build_auth_router, make_current_user_dependency
from backend.core.agent_manifest import all_agent_manifests
from backend.core.execution import ExecutionEngine
from backend.core.repository import RunRecord, get_repository, utc_now
from backend.core.registry import AGENT_REGISTRY, capability_matrix
from backend.core.service_manifest import all_service_manifests
from backend.core.settings import get_settings, load_env_file
from backend.services.catalog import DatasetCatalogService, UnifiedDatasetSearchService
from backend.services.credentials import (
    build_discovery_service_for,
    build_skill_orchestrator_for,
)
from backend.services.dataset_processing import DatasetProcessingService
from backend.services.ingestion import DatasetIngestionService
from backend.vault import ProviderVault, VaultKeyMissing, VaultStore
from backend.vault.crypto import SecretBox
from backend.vault.web import build_settings_router
from planner.planner import RuleBasedPlanner
from planner.workflow_library import WORKFLOW_LIBRARY
from router.hybrid_router import HybridRouter

configure_logging()
load_env_file()
security_config = SecurityConfig.from_env()
cors_origins = list(
    dict.fromkeys(
        [
            *security_config.cors_origins,
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8080",
            "http://localhost:8080",
        ]
    )
)
cors_origin_regex = os.getenv(
    "DATAFORGE_CORS_ORIGIN_REGEX",
    r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?",
)

app = FastAPI(
    title="DataForge AI",
    description="Autonomous AI Data Engineering Platform",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(build_security_middleware(security_config))

health_service = HealthService()
auth_store = AuthStore(os.getenv("DATAFORGE_AUTH_DB", "tmp/dataforge_auth.db"))
auth_service = AuthService(auth_store)
app.include_router(build_auth_router(auth_service))
current_user = make_current_user_dependency(auth_service)
team_service = TeamService(TeamStore(os.getenv("DATAFORGE_TEAMS_DB", "tmp/dataforge_teams.db")))

try:
    provider_vault = ProviderVault(
        VaultStore(os.getenv("DATAFORGE_VAULT_DB", "tmp/dataforge_vault.db")),
        SecretBox.from_env(),
    )
except VaultKeyMissing:
    provider_vault = None
app.include_router(build_settings_router(lambda: provider_vault, current_user))


def optional_user(request: Request):
    """Return the authenticated user when a session cookie exists, else None."""
    return auth_service.authenticate(request.cookies.get(SESSION_COOKIE))


def repository():
    """Create the configured repository boundary."""
    return get_repository()


health_service.register("repository", make_sqlite_check(repository()))


def safe_task_id(task_id: str) -> str:
    """Return a validated task id suitable for artifact path lookup."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise HTTPException(status_code=400, detail="Invalid task id.")
    return task_id


def require_access(
    record: object | None,
    resource_type: str,
    id_field: str,
    user: object,
    *,
    need: str = "view",
    missing_detail: str = "Resource not found.",
) -> object:
    """Return a record only when the authenticated user has team-aware access."""
    if record is None:
        raise HTTPException(status_code=404, detail=missing_detail)
    try:
        return assert_can(record, resource_type, id_field, user, team_service, need=need)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def run_for_task_or_404(task_id: str, user: object, *, need: str = "view") -> RunRecord:
    """Resolve a workflow/upload run by task id and enforce team-aware access."""
    run = repository().get_run(task_id)
    return require_access(
        run,
        "run",
        "task_id",
        user,
        need=need,
        missing_detail="Run not found.",
    )  # type: ignore[return-value]


def validated_project_id(project_id: object, user: object) -> str | None:
    """Validate optional project linkage before a run is attached to it."""
    if project_id in (None, ""):
        return None
    project_id_str = str(project_id)
    require_access(
        repository().get_project(project_id_str),
        "project",
        "project_id",
        user,
        need="edit",
        missing_detail="Project not found.",
    )
    return project_id_str


def _team_error(exc: Exception) -> HTTPException:
    """Map team-domain errors to HTTP statuses."""
    if isinstance(exc, TeamNotFound):
        return HTTPException(status_code=404, detail="Team not found.")
    if isinstance(exc, (NotATeamMember, InsufficientTeamRole, PermissionDenied)):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _team_json(team: object) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "owner_id": team.owner_id,
        "created_at": team.created_at,
    }


def _member_json(member: object) -> dict:
    return {
        "team_id": member.team_id,
        "user_id": member.user_id,
        "team_role": member.team_role,
        "created_at": member.created_at,
    }


def _share_json(share: object) -> dict:
    return {
        "resource_type": share.resource_type,
        "resource_id": share.resource_id,
        "team_id": share.team_id,
        "permission": share.permission,
        "created_at": share.created_at,
    }


def _stage_trace_item(
    name: str,
    *,
    engine: str,
    status: str = "completed",
    output: dict | None = None,
    skipped: bool = False,
) -> dict:
    """Small persisted trace item for Pipeline and run-detail views."""
    return {
        "name": name,
        "engine": engine,
        "status": "skipped" if skipped else status,
        "output": output or {},
    }


def _upload_stage_trace(result: dict, catalog_record: object) -> list[dict]:
    """Build the honest 7-stage trace for an uploaded dataset package run."""
    summary = result.get("summary", {})
    quality = result.get("quality_report", {})
    artifacts = result.get("artifacts", {})
    ai_provider = getattr(catalog_record, "ai_provider", "local")
    return [
        _stage_trace_item(
            "Requirement Analyzer",
            engine="deterministic",
            output={"request": result.get("request") or "Analyze uploaded dataset."},
        ),
        _stage_trace_item(
            "Planner",
            engine="deterministic",
            output={"workflow": "uploaded_dataset_package", "active_stages": 7},
        ),
        _stage_trace_item(
            "Discovery / Ingestion",
            engine="dataset_processing_service",
            output={
                "filename": result.get("ingestion", {}).get("filename"),
                "rows": summary.get("rows"),
                "columns": summary.get("columns"),
            },
        ),
        _stage_trace_item(
            "Quality Evaluator",
            engine="deterministic_quality_metrics",
            output={
                "score": quality.get("score"),
                "metrics": quality.get("metrics", {}),
            },
        ),
        _stage_trace_item(
            "AI Skills",
            engine=str(ai_provider),
            output={"summary_provider": ai_provider},
        ),
        _stage_trace_item(
            "Packaging",
            engine="packaging_services",
            output={
                "dataset_zip": artifacts.get("dataset_zip"),
                "manifest": artifacts.get("manifest"),
            },
        ),
        _stage_trace_item(
            "Explainability",
            engine=str(ai_provider),
            output={
                "dataset_card": bool(getattr(catalog_record, "dataset_card", "")),
                "quality_narrative": bool(getattr(catalog_record, "quality_narrative", "")),
            },
        ),
    ]


def _execution_stage_trace(execution: object) -> list[dict]:
    """Convert registry-agent messages into a persisted trace."""
    trace = []
    for message in getattr(execution, "messages", ()):
        result = message.result if isinstance(message.result, dict) else {}
        trace.append(
            _stage_trace_item(
                message.agent,
                engine="registry_agent",
                status=str(message.status.value if hasattr(message.status, "value") else message.status),
                output={
                    "confidence": message.confidence,
                    "next_action": (
                        message.next_action.value
                        if hasattr(message.next_action, "value")
                        else str(message.next_action)
                    ),
                    **result,
                },
            )
        )
    return trace


def _resource_for_share(resource_type: str, resource_id: str) -> tuple[object | None, str]:
    """Resolve a shareable resource and return (record, id_field)."""
    repo = repository()
    if resource_type == "dataset":
        return repo.get_dataset(resource_id), "dataset_id"
    if resource_type == "project":
        return repo.get_project(resource_id), "project_id"
    if resource_type == "run":
        return repo.get_run(resource_id), "task_id"
    raise HTTPException(status_code=400, detail="Unsupported resource type.")


@app.get("/health")
def health() -> dict:
    payload = health_service.liveness()
    payload["service"] = "dataforge-ai"
    return payload


@app.get("/ready")
def ready() -> dict:
    """Return readiness checks for runtime dependencies."""
    return health_service.readiness()


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


@app.post("/teams")
def create_team(payload: dict, user=Depends(current_user)) -> dict:
    """Create a team and enroll the creator as owner."""
    try:
        team = team_service.create_team(
            name=str(payload.get("name", "Untitled Team")),
            user=user,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to client error
        raise _team_error(exc) from exc
    return _team_json(team)


@app.get("/teams")
def list_teams(user=Depends(current_user)) -> dict:
    """List teams the current user belongs to."""
    return {
        "teams": [
            _team_json(team)
            for team in team_service.list_teams_for_user(user)
        ]
    }


@app.delete("/teams/{team_id}")
def delete_team(team_id: str, user=Depends(current_user)) -> dict:
    """Delete a team. Only the team owner or a global admin may delete."""
    try:
        team_service.delete_team(team_id, user)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return {"ok": True, "team_id": team_id, "removed": True}


@app.get("/teams/{team_id}/members")
def list_team_members(team_id: str, user=Depends(current_user)) -> dict:
    """List team members for a team the user belongs to."""
    try:
        members = team_service.list_members(team_id, user)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return {"team_id": team_id, "members": [_member_json(member) for member in members]}


@app.post("/teams/{team_id}/members")
def add_team_member(team_id: str, payload: dict, user=Depends(current_user)) -> dict:
    """Add or update a team member by user_id or email."""
    target_user_id = str(payload.get("user_id") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    if not target_user_id and email:
        rec = auth_store.get_user_by_email(email)
        if rec is None:
            raise HTTPException(status_code=404, detail="User not found.")
        target_user_id = rec.id
    if not target_user_id:
        raise HTTPException(status_code=400, detail="user_id or email is required.")
    try:
        member = team_service.add_member(
            team_id,
            target_user_id,
            str(payload.get("role") or payload.get("team_role") or "member"),
            user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return _member_json(member)


@app.delete("/teams/{team_id}/members/{user_id}")
def remove_team_member(team_id: str, user_id: str, user=Depends(current_user)) -> dict:
    """Remove a member from a team. The team owner cannot be removed."""
    try:
        team_service.remove_member(team_id, user_id, user)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return {"ok": True, "team_id": team_id, "user_id": user_id, "removed": True}


@app.post("/teams/{team_id}/shares")
def share_team_resource(team_id: str, payload: dict, user=Depends(current_user)) -> dict:
    """Share a dataset/project/run with a team."""
    resource_type = str(payload.get("resource_type") or "").strip().lower()
    resource_id = str(payload.get("resource_id") or "").strip()
    permission = str(payload.get("permission") or "view").strip().lower()
    record, id_field = _resource_for_share(resource_type, resource_id)
    require_access(
        record,
        resource_type,
        id_field,
        user,
        need="edit",
        missing_detail="Resource not found.",
    )
    try:
        share = team_service.share_resource(
            resource_type,
            resource_id,
            team_id,
            permission,
            user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return _share_json(share)


@app.get("/teams/{team_id}/shares")
def list_team_shares(team_id: str, user=Depends(current_user)) -> dict:
    """List resources shared with a team."""
    try:
        shares = team_service.list_shares(team_id, user)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return {"team_id": team_id, "shares": [_share_json(share) for share in shares]}


@app.delete("/teams/{team_id}/shares")
def unshare_team_resource(
    team_id: str,
    resource_type: str,
    resource_id: str,
    user=Depends(current_user),
) -> dict:
    """Remove a team share from a dataset/project/run."""
    resource_type = resource_type.strip().lower()
    record, id_field = _resource_for_share(resource_type, resource_id)
    require_access(
        record,
        resource_type,
        id_field,
        user,
        need="edit",
        missing_detail="Resource not found.",
    )
    try:
        team_service.unshare_resource(resource_type, resource_id, team_id, user)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP
        raise _team_error(exc) from exc
    return {
        "ok": True,
        "team_id": team_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "removed": True,
    }


def _discovery_response(
    payload: dict,
    query_override: str | None = None,
    user: object | None = None,
) -> dict:
    """Search dataset providers and return ranked candidates without ingestion."""
    planner = RuleBasedPlanner()
    plan = planner.plan(payload)
    service = build_discovery_service_for(user, provider_vault)
    query = str(
        query_override
        or plan.structured_requirement.get("raw_request")
        or plan.structured_requirement.get("domain")
        or payload.get("query")
        or payload.get("request")
        or ""
    )
    intensity = str(payload.get("intensity") or payload.get("search_intensity") or "medium")
    discovery_payload = service.search(
        query,
        intensity=intensity,
        limit=int(payload.get("limit", 10)),
    )
    candidates = discovery_payload.get("results", [])
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
        "discovery": discovery_payload,
    }


@app.post("/discovery/search")
def discovery_search(payload: dict, user=Depends(optional_user)) -> dict:
    """Search dataset providers and return ranked candidates without ingestion."""
    return _discovery_response(payload, user=user)


@app.get("/discovery/search")
def discovery_search_get(
    q: str = "",
    intensity: str = "medium",
    limit: int = 10,
    user=Depends(optional_user),
) -> dict:
    """GET variant used by static frontends and smoke tests."""
    return _discovery_response(
        {"request": q, "query": q, "intensity": intensity, "limit": limit},
        query_override=q,
        user=user,
    )


@app.get("/discovery/providers")
def discovery_providers(user=Depends(optional_user)) -> dict:
    """Return configured discovery providers and last error state."""
    service = build_discovery_service_for(user, provider_vault)
    return service.provider_status()


@app.post("/datasets/ingest")
def ingest_dataset(payload: dict, user=Depends(current_user)) -> dict:
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
def process_dataset(payload: dict, user=Depends(current_user)) -> dict:
    """Ingest uploaded dataset content and generate reports, manifest, and ZIP."""
    settings = get_settings()
    project_id = validated_project_id(payload.get("project_id"), user)
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
    repo = repository()
    orchestrator = build_skill_orchestrator_for(user, provider_vault)
    catalog_record = DatasetCatalogService(repo, orchestrator=orchestrator).index_processed_upload(
        result,
        user_id=user.id,
    )
    result["request"] = str(payload.get("request", "Analyze uploaded dataset."))
    stage_trace = _upload_stage_trace(result, catalog_record)
    repo.save_run(
        RunRecord(
            task_id=result["task_id"],
            project_id=project_id,
            workflow="dataset_process",
            status=result.get("status", "completed"),
            request=payload,
            artifacts=result.get("artifacts", {}),
            created_at=utc_now(),
            completed_at=utc_now(),
            stage_trace=stage_trace,
            user_id=user.id,
        )
    )
    result["catalog_record"] = {
        "id": catalog_record.dataset_id,
        "title": catalog_record.title,
        "source": catalog_record.source,
    }
    result["stage_trace"] = stage_trace
    return result


@app.get("/datasets/catalog")
def list_dataset_catalog(user=Depends(current_user)) -> dict:
    """List uploaded datasets indexed in the local catalog."""
    catalog = DatasetCatalogService(repository())
    records = visible_records(
        repository().list_datasets(),
        "dataset",
        "dataset_id",
        user,
        team_service,
        need="view",
    )
    return {"datasets": [catalog._record_to_dict(record) for record in records]}


@app.post("/datasets/search")
def search_datasets(payload: dict, user=Depends(optional_user)) -> dict:
    """Search user-visible local datasets plus optional public providers.

    Anonymous callers can use public discovery from the Discover page. Local
    catalog results remain scoped to the authenticated user and their team
    shares.
    """
    orchestrator = build_skill_orchestrator_for(user, provider_vault)
    repo = repository()
    visible_dataset_ids: set[str] = set()
    if user is not None:
        visible_dataset_ids = {
            record.dataset_id
            for record in visible_records(
                repo.list_datasets(),
                "dataset",
                "dataset_id",
                user,
                team_service,
                need="view",
            )
        }
    catalog = DatasetCatalogService(repo, orchestrator=orchestrator)
    discovery = build_discovery_service_for(user, provider_vault)
    service = UnifiedDatasetSearchService(catalog, discovery=discovery)
    limit_value = payload.get("limit")
    return service.search(
        query=str(payload.get("query", "")),
        include_public=bool(payload.get("include_public", False)),
        limit=int(limit_value) if limit_value is not None else None,
        intensity=str(payload.get("intensity") or payload.get("search_intensity") or "medium"),
        allowed_dataset_ids=visible_dataset_ids,
    )


@app.post("/datasets/save-public")
def save_public_dataset(payload: dict, user=Depends(current_user)) -> dict:
    """Save a public discovery/search result into the user's catalog."""
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else payload
    try:
        record = DatasetCatalogService(repository()).save_public_candidate(
            candidate,
            user_id=user.id,
            query=str(payload.get("query") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dataset": DatasetCatalogService(repository())._record_to_dict(record)}


@app.post("/projects")
def create_project(payload: dict, user=Depends(current_user)) -> dict:
    """Create a DataForge project."""
    repo = repository()
    project = repo.create_project(
        name=str(payload.get("name", "Untitled DataForge Project")),
        quality_profile=str(payload.get("quality_profile", "production")),
        target_model=str(payload.get("target_model", "nemotron")),
        user_id=user.id,
    )
    return project.__dict__


@app.get("/projects")
def list_projects(user=Depends(current_user)) -> dict:
    """List DataForge projects."""
    repo = repository()
    projects = visible_records(
        repo.list_projects(),
        "project",
        "project_id",
        user,
        team_service,
        need="view",
    )
    return {"projects": [project.__dict__ for project in projects]}


@app.get("/projects/{project_id}")
def get_project(project_id: str, user=Depends(current_user)) -> dict:
    """Return a DataForge project and its workflow runs."""
    repo = repository()
    project = require_access(
        repo.get_project(project_id),
        "project",
        "project_id",
        user,
        need="view",
        missing_detail="Project not found.",
    )
    runs = visible_records(
        repo.list_runs(project_id),
        "run",
        "task_id",
        user,
        team_service,
        need="view",
    )
    return {
        "project": project.__dict__,
        "runs": [run.__dict__ for run in runs],
    }


@app.post("/workflow/start")
def start_workflow(payload: dict, user=Depends(current_user)) -> dict:
    """Plan, validate, execute, report, and package a dataset workflow."""
    project_id = validated_project_id(payload.get("project_id"), user)
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
            project_id=project_id,
            workflow=execution.workflow,
            status=execution.status,
            request=payload,
            artifacts=execution.artifacts,
            created_at=utc_now(),
            completed_at=utc_now(),
            stage_trace=_execution_stage_trace(execution),
            user_id=user.id,
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
def workflow_status(task_id: str, user=Depends(current_user)) -> dict:
    """Return persisted workflow run status."""
    run = run_for_task_or_404(safe_task_id(task_id), user)
    return {"run": run.__dict__}


@app.get("/workflow/runs")
def list_workflow_runs(project_id: str | None = None, user=Depends(current_user)) -> dict:
    """List persisted workflow runs, optionally filtered by project."""
    repo = repository()
    runs = visible_records(
        repo.list_runs(project_id),
        "run",
        "task_id",
        user,
        team_service,
        need="view",
    )
    return {"runs": [run.__dict__ for run in runs]}


@app.get("/workflow/runs/{task_id}")
def get_workflow_run(task_id: str, user=Depends(current_user)) -> dict:
    """Return a persisted run with its stage trace for the Pipeline page."""
    run = run_for_task_or_404(safe_task_id(task_id), user)
    return {"run": run.__dict__, "stage_trace": run.stage_trace}


@app.get("/router/status")
def router_status() -> dict:
    """Return provider routing policy and current in-memory provider stats."""
    router = HybridRouter()
    return router.status()


@app.get("/ai/llm/status")
def llm_status(user=Depends(optional_user)) -> dict:
    """Return LLM skill orchestrator provider priority and health."""
    return build_skill_orchestrator_for(user, provider_vault).status()


@app.get("/reports/{task_id}")
def list_reports(task_id: str, user=Depends(current_user)) -> dict:
    """List generated report files for an execution task."""
    task_id = safe_task_id(task_id)
    run_for_task_or_404(task_id, user)
    reports_dir = get_settings().storage.artifacts_root / task_id / "reports"
    reports = []
    if reports_dir.exists():
        reports = [path.name for path in sorted(reports_dir.glob("*.md"))]
    return {"task_id": task_id, "reports": reports}


@app.get("/artifacts/{task_id}/dataset.zip")
def download_dataset_zip(task_id: str, user=Depends(current_user)) -> FileResponse:
    """Download a packaged dataset ZIP for an execution task."""
    task_id = safe_task_id(task_id)
    run_for_task_or_404(task_id, user)
    zip_path = get_settings().storage.artifacts_root / task_id / "dataset.zip"
    return FileResponse(zip_path, filename="dataset.zip", media_type="application/zip")
