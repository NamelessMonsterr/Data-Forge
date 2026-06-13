"""Repository boundary for projects, workflow runs, and dataset catalog.

This module keeps the original ``JsonRepository`` (now demoted to a dev-only
backend) and adds ``SqlRepository`` -- a transactional, concurrency-safe store
built on stdlib ``sqlite3`` with WAL journaling and explicit ``BEGIN IMMEDIATE``
write transactions. ``get_repository()`` selects the backend from the
``DATAFORGE_PERSISTENCE`` environment variable (defaults to ``sqlite``).

The SQLite schema is derived from the record dataclasses by reflection, and a
minimal idempotent migration adds any dataclass field that is missing from an
existing table -- so adding a field (e.g. ``quality_narrative``) needs no manual
DDL. Nested ``dict``/``list`` fields are stored as JSON text columns.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Records (unchanged identity; DatasetCatalogRecord includes the shipped
# quality_narrative / quality_metrics / dataset_card fields).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProjectRecord:
    """Persisted project metadata."""

    project_id: str
    name: str
    status: str
    quality_profile: str
    target_model: str
    created_at: str
    user_id: str | None = None


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
    user_id: str | None = None


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
    quality_narrative: str = ""
    quality_metrics: dict[str, Any] = field(default_factory=dict)
    dataset_card: str = ""
    user_id: str | None = None


@dataclass
class RepositorySnapshot:
    """In-memory shape stored by the JSON repository."""

    projects: dict[str, ProjectRecord] = field(default_factory=dict)
    runs: dict[str, RunRecord] = field(default_factory=dict)
    datasets: dict[str, DatasetCatalogRecord] = field(default_factory=dict)


# Table name -> (record class, primary-key field name)
_RECORD_TABLES: dict[str, tuple[type, str]] = {
    "projects": (ProjectRecord, "project_id"),
    "runs": (RunRecord, "task_id"),
    "datasets": (DatasetCatalogRecord, "dataset_id"),
}


def _is_json_field(type_str: Any) -> bool:
    t = str(type_str)
    return "dict" in t or "list" in t


def _sql_type(type_str: Any) -> str:
    t = str(type_str)
    if _is_json_field(t):
        return "TEXT"
    if "bool" in t:
        return "INTEGER"
    if "int" in t:
        return "INTEGER"
    if "float" in t:
        return "REAL"
    return "TEXT"


def _encode(record: Any) -> dict[str, Any]:
    """Dataclass -> column dict, JSON-encoding nested dict/list fields."""
    out: dict[str, Any] = {}
    for f in fields(record):
        val = getattr(record, f.name)
        if _is_json_field(f.type):
            out[f.name] = json.dumps(val)
        elif isinstance(val, bool):
            out[f.name] = int(val)
        else:
            out[f.name] = val
    return out


def _decode(cls: type, row: sqlite3.Row) -> Any:
    """Row -> dataclass, JSON-decoding nested dict/list fields."""
    field_map = {f.name: f for f in fields(cls)}
    kwargs: dict[str, Any] = {}
    for key in row.keys():
        f = field_map.get(key)
        if f is None:
            continue
        val = row[key]
        if _is_json_field(f.type) and val is not None:
            val = json.loads(val)
        kwargs[key] = val
    return cls(**kwargs)


# --------------------------------------------------------------------------- #
# Dev-only JSON repository (kept for backward compatibility / local dev).
# Not concurrency-safe: read-modify-write loses interleaved writes.
# --------------------------------------------------------------------------- #
class JsonRepository:
    """Single-file JSON repository. DEV ONLY -- not safe under concurrency."""

    def __init__(self, path: Path | str = "tmp/dataforge_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        name: str,
        quality_profile: str = "production",
        target_model: str = "nemotron",
        user_id: str | None = None,
    ) -> ProjectRecord:
        snapshot = self._load()
        project = ProjectRecord(
            project_id=f"project-{uuid4().hex[:12]}",
            name=name,
            status="active",
            quality_profile=quality_profile,
            target_model=target_model,
            created_at=utc_now(),
            user_id=user_id,
        )
        snapshot.projects[project.project_id] = project
        self._save(snapshot)
        return project

    def list_projects(self) -> list[ProjectRecord]:
        return list(self._load().projects.values())

    def get_project(self, project_id: str) -> ProjectRecord | None:
        return self._load().projects.get(project_id)

    def save_run(self, run: RunRecord) -> RunRecord:
        snapshot = self._load()
        snapshot.runs[run.task_id] = run
        self._save(snapshot)
        return run

    def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        runs = list(self._load().runs.values())
        if project_id is None:
            return runs
        return [run for run in runs if run.project_id == project_id]

    def get_run(self, task_id: str) -> RunRecord | None:
        return self._load().runs.get(task_id)

    def save_dataset(self, dataset: DatasetCatalogRecord) -> DatasetCatalogRecord:
        snapshot = self._load()
        snapshot.datasets[dataset.dataset_id] = dataset
        self._save(snapshot)
        return dataset

    def list_datasets(self) -> list[DatasetCatalogRecord]:
        return list(self._load().datasets.values())

    def get_dataset(self, dataset_id: str) -> DatasetCatalogRecord | None:
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
            dataset_id: DatasetCatalogRecord(
                **{"ai_summary": "", "ai_provider": "local", **payload}
            )
            for dataset_id, payload in raw.get("datasets", {}).items()
        }
        return RepositorySnapshot(projects=projects, runs=runs, datasets=datasets)

    def _save(self, snapshot: RepositorySnapshot) -> None:
        payload = {
            "projects": {pid: p.__dict__ for pid, p in snapshot.projects.items()},
            "runs": {tid: r.__dict__ for tid, r in snapshot.runs.items()},
            "datasets": {did: d.__dict__ for did, d in snapshot.datasets.items()},
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Production repository: transactional, concurrency-safe SQLite (WAL).
# --------------------------------------------------------------------------- #
class SqlRepository:
    """Transactional SQLite repository safe under concurrent access.

    Each write runs in its own ``BEGIN IMMEDIATE`` transaction; WAL journaling
    plus a busy timeout serializes writers without losing updates, and allows
    concurrent readers. The same public surface as ``JsonRepository`` so it is a
    drop-in replacement. Swapping to Postgres later only requires reimplementing
    ``_connect`` / SQL dialect behind this same interface.
    """

    def __init__(self, path: Path | str = "tmp/dataforge.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            conn = self._connect()
            try:
                for table, (cls, pk) in _RECORD_TABLES.items():
                    cols = []
                    for f in fields(cls):
                        pk_part = " PRIMARY KEY" if f.name == pk else ""
                        cols.append(f'"{f.name}" {_sql_type(f.type)}{pk_part}')
                    conn.execute(
                        f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(cols)})'
                    )
                    # Idempotent migration: add any field missing from the table.
                    existing = {
                        r["name"]
                        for r in conn.execute(f'PRAGMA table_info("{table}")')
                    }
                    for f in fields(cls):
                        if f.name not in existing:
                            conn.execute(
                                f'ALTER TABLE "{table}" '
                                f'ADD COLUMN "{f.name}" {_sql_type(f.type)}'
                            )
                    # Helpful secondary index for catalog ordering.
                    if "created_at" in {f.name for f in fields(cls)}:
                        conn.execute(
                            f'CREATE INDEX IF NOT EXISTS "idx_{table}_created_at" '
                            f'ON "{table}" ("created_at")'
                        )
            finally:
                conn.close()

    def _write(self, op: Callable[[sqlite3.Connection], Any]) -> Any:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = op(conn)
                conn.execute("COMMIT")
                return result
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def _upsert(self, table: str, pk: str, record: Any) -> Any:
        data = _encode(record)
        cols = list(data.keys())
        collist = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f'"{c}"=excluded."{c}"' for c in cols if c != pk)
        sql = (
            f'INSERT INTO "{table}" ({collist}) VALUES ({placeholders}) '
            f'ON CONFLICT("{pk}") DO UPDATE SET {updates}'
        )
        params = [data[c] for c in cols]
        self._write(lambda conn: conn.execute(sql, params))
        return record

    def _all(self, table: str, cls: type) -> list[Any]:
        conn = self._connect()
        try:
            return [_decode(cls, r) for r in conn.execute(f'SELECT * FROM "{table}"')]
        finally:
            conn.close()

    def _get(self, table: str, cls: type, pk: str, key: str) -> Any | None:
        conn = self._connect()
        try:
            row = conn.execute(
                f'SELECT * FROM "{table}" WHERE "{pk}"=?', (key,)
            ).fetchone()
            return _decode(cls, row) if row else None
        finally:
            conn.close()

    # -- Public surface (mirrors JsonRepository) ------------------------- #
    def create_project(
        self,
        name: str,
        quality_profile: str = "production",
        target_model: str = "nemotron",
        user_id: str | None = None,
    ) -> ProjectRecord:
        project = ProjectRecord(
            project_id=f"project-{uuid4().hex[:12]}",
            name=name,
            status="active",
            quality_profile=quality_profile,
            target_model=target_model,
            created_at=utc_now(),
            user_id=user_id,
        )
        return self._upsert("projects", "project_id", project)

    def list_projects(self) -> list[ProjectRecord]:
        return self._all("projects", ProjectRecord)

    def get_project(self, project_id: str) -> ProjectRecord | None:
        return self._get("projects", ProjectRecord, "project_id", project_id)

    def save_run(self, run: RunRecord) -> RunRecord:
        return self._upsert("runs", "task_id", run)

    def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        runs = self._all("runs", RunRecord)
        if project_id is None:
            return runs
        return [run for run in runs if run.project_id == project_id]

    def get_run(self, task_id: str) -> RunRecord | None:
        return self._get("runs", RunRecord, "task_id", task_id)

    def save_dataset(self, dataset: DatasetCatalogRecord) -> DatasetCatalogRecord:
        return self._upsert("datasets", "dataset_id", dataset)

    def list_datasets(self) -> list[DatasetCatalogRecord]:
        return self._all("datasets", DatasetCatalogRecord)

    def get_dataset(self, dataset_id: str) -> DatasetCatalogRecord | None:
        return self._get("datasets", DatasetCatalogRecord, "dataset_id", dataset_id)


def get_repository(path: Path | str | None = None) -> Any:
    """Return the configured repository backend.

    ``DATAFORGE_PERSISTENCE=sqlite`` (default) -> :class:`SqlRepository`.
    ``DATAFORGE_PERSISTENCE=json`` -> :class:`JsonRepository` (dev only).
    """
    backend = os.getenv("DATAFORGE_PERSISTENCE", "sqlite").strip().lower()
    if backend == "json":
        return JsonRepository(path or "tmp/dataforge_state.json")
    return SqlRepository(path or os.getenv("DATAFORGE_DB_PATH", "tmp/dataforge.db"))
