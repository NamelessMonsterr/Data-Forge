"""Repository boundary for projects and workflow runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProjectRecord:
    """Persisted project metadata."""

    project_id: str
    name: str
    status: str
    quality_profile: str
    target_model: str
    created_at: str


@dataclass(frozen=True)
class RunRecord:
    """Persisted workflow execution metadata."""

    task_id: str
    project_id: str | None
    workflow: str
    status: str
    request: dict[str, Any]
    artifacts: dict[str, str]
    created_at: str
    completed_at: str | None = None


@dataclass(frozen=True)
class DatasetCatalogRecord:
    """Persisted searchable metadata for uploaded or discovered datasets."""

    dataset_id: str
    title: str
    source: str
    provider: str
    task_id: str | None
    filename: str
    format: str
    rows: int
    columns: int
    schema: dict[str, Any]
    stats: dict[str, Any]
    artifacts: dict[str, str]
    quality_score: int | None
    tags: list[str]
    description: str
    created_at: str
    ai_summary: str = ""
    ai_provider: str = "local"


@dataclass
class RepositorySnapshot:
    """In-memory shape stored by the JSON repository."""

    projects: dict[str, ProjectRecord] = field(default_factory=dict)
    runs: dict[str, RunRecord] = field(default_factory=dict)
    datasets: dict[str, DatasetCatalogRecord] = field(default_factory=dict)


class JsonRepository:
    """Small durable repository used until Postgres is configured."""

    def __init__(self, path: Path | str = "tmp/dataforge_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        name: str,
        quality_profile: str = "production",
        target_model: str = "nemotron",
    ) -> ProjectRecord:
        """Create and persist a project record."""
        snapshot = self._load()
        project = ProjectRecord(
            project_id=f"project-{uuid4().hex[:12]}",
            name=name,
            status="active",
            quality_profile=quality_profile,
            target_model=target_model,
            created_at=utc_now(),
        )
        snapshot.projects[project.project_id] = project
        self._save(snapshot)
        return project

    def list_projects(self) -> list[ProjectRecord]:
        """Return all persisted projects."""
        return list(self._load().projects.values())

    def get_project(self, project_id: str) -> ProjectRecord | None:
        """Return a project by id."""
        return self._load().projects.get(project_id)

    def save_run(self, run: RunRecord) -> RunRecord:
        """Persist workflow run metadata."""
        snapshot = self._load()
        snapshot.runs[run.task_id] = run
        self._save(snapshot)
        return run

    def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        """Return persisted runs, optionally filtered by project."""
        runs = list(self._load().runs.values())
        if project_id is None:
            return runs
        return [run for run in runs if run.project_id == project_id]

    def get_run(self, task_id: str) -> RunRecord | None:
        """Return a workflow run by task id."""
        return self._load().runs.get(task_id)

    def save_dataset(self, dataset: DatasetCatalogRecord) -> DatasetCatalogRecord:
        """Persist searchable dataset catalog metadata."""
        snapshot = self._load()
        snapshot.datasets[dataset.dataset_id] = dataset
        self._save(snapshot)
        return dataset

    def list_datasets(self) -> list[DatasetCatalogRecord]:
        """Return all cataloged datasets."""
        return list(self._load().datasets.values())

    def get_dataset(self, dataset_id: str) -> DatasetCatalogRecord | None:
        """Return one cataloged dataset by id."""
        return self._load().datasets.get(dataset_id)

    def _load(self) -> RepositorySnapshot:
        if not self.path.exists():
            return RepositorySnapshot()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        projects = {
            project_id: ProjectRecord(**payload)
            for project_id, payload in raw.get("projects", {}).items()
        }
        runs = {
            task_id: RunRecord(**payload)
            for task_id, payload in raw.get("runs", {}).items()
        }
        datasets = {
            dataset_id: DatasetCatalogRecord(**{"ai_summary": "", "ai_provider": "local", **payload})
            for dataset_id, payload in raw.get("datasets", {}).items()
        }
        return RepositorySnapshot(projects=projects, runs=runs, datasets=datasets)

    def _save(self, snapshot: RepositorySnapshot) -> None:
        payload = {
            "projects": {
                project_id: project.__dict__
                for project_id, project in snapshot.projects.items()
            },
            "runs": {
                task_id: run.__dict__
                for task_id, run in snapshot.runs.items()
            },
            "datasets": {
                dataset_id: dataset.__dict__
                for dataset_id, dataset in snapshot.datasets.items()
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
