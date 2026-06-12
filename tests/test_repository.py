"""Repository tests for project and run persistence."""

from pathlib import Path

from backend.core.repository import DatasetCatalogRecord, JsonRepository, RunRecord, utc_now


def test_json_repository_persists_projects_and_runs(tmp_path: Path):
    """Projects and workflow runs should survive repository re-instantiation."""
    state_path = tmp_path / "state.json"
    repo = JsonRepository(state_path)
    project = repo.create_project("Healthcare Dataset")
    run = RunRecord(
        task_id="task-1",
        project_id=project.project_id,
        workflow="full_search_improve_export",
        status="completed",
        request={"request": "Build a dataset"},
        artifacts={"dataset_zip": "dataset.zip"},
        created_at=utc_now(),
        completed_at=utc_now(),
    )
    repo.save_run(run)
    dataset = DatasetCatalogRecord(
        dataset_id="local-1",
        title="Healthcare Upload",
        source="local_upload",
        provider="local",
        task_id=run.task_id,
        filename="healthcare.csv",
        format="csv",
        rows=2,
        columns=3,
        schema={"instruction": {"type": "string"}},
        stats={"missing_cells": 0},
        artifacts={"dataset_zip": "dataset.zip"},
        quality_score=91,
        tags=["healthcare", "instruction"],
        description="Healthcare uploaded dataset.",
        created_at=utc_now(),
    )
    repo.save_dataset(dataset)

    reloaded = JsonRepository(state_path)

    assert reloaded.get_project(project.project_id) == project
    assert reloaded.get_run("task-1") == run
    assert reloaded.list_runs(project.project_id) == [run]
    assert reloaded.get_dataset("local-1") == dataset
    assert reloaded.list_datasets() == [dataset]
