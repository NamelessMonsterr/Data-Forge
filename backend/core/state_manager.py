"""Execution state manager for workflow progress and history."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.core.protocol import AgentMessage


@dataclass
class WorkflowProgress:
    """Runtime progress tracked for one workflow execution."""

    task_id: str
    current_node: str | None = None
    completed_nodes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    quality_history: list[dict[str, Any]] = field(default_factory=list)
    routing_history: list[dict[str, Any]] = field(default_factory=list)


class StateManager:
    """Manage execution progress independently from agent implementations."""

    def __init__(self) -> None:
        self._progress: dict[str, WorkflowProgress] = {}

    def start(self, task_id: str) -> WorkflowProgress:
        """Start progress tracking for a task."""
        progress = WorkflowProgress(task_id=task_id)
        self._progress[task_id] = progress
        return progress

    def record_node_start(self, task_id: str, node: str) -> None:
        """Record the node currently running."""
        self._progress[task_id].current_node = node

    def record_message(self, task_id: str, node: str, message: AgentMessage) -> None:
        """Record agent completion, failures, and quality history."""
        progress = self._progress[task_id]
        progress.completed_nodes.append(node)
        progress.current_node = None
        if message.status.value in {"FAIL", "ERROR"}:
            progress.failures.append(node)
        if message.agent == "quality_evaluator" and isinstance(message.result, dict):
            progress.quality_history.append(message.result.get("quality_report", {}))

    def get(self, task_id: str) -> WorkflowProgress | None:
        """Return progress for a task."""
        return self._progress.get(task_id)
