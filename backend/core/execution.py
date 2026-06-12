"""Linear execution engine for validated DataForge workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agents.demo.agent import DemoAgentFactory
from backend.core.protocol import AgentMessage, NextAction
from backend.core.state_manager import StateManager, WorkflowProgress
from planner.graph_validator import validate_graph
from planner.workflow_library import Node, Workflow


@dataclass
class ExecutionState:
    """Mutable execution state passed between workflow agents."""

    task_id: str
    request: dict[str, Any]
    artifacts_dir: Path
    data: dict[str, Any] = field(default_factory=dict)
    history: list[AgentMessage] = field(default_factory=list)

    def record(self, message: AgentMessage) -> None:
        """Append an agent message and merge dictionary results into state."""
        self.history.append(message)
        if isinstance(message.result, dict):
            self.data.update(message.result)


@dataclass(frozen=True)
class ExecutionResult:
    """Final response returned by the execution engine."""

    task_id: str
    workflow: str
    status: str
    messages: tuple[AgentMessage, ...]
    artifacts: dict[str, str]
    state: dict[str, Any]
    progress: WorkflowProgress | None = None


AgentFactory = Callable[[Node], Any]


class ExecutionEngine:
    """Execute validated linear workflows through registry-backed agents."""

    def __init__(
        self,
        artifacts_root: Path | str = "tmp/dataforge_runs",
        agent_factory: AgentFactory | None = None,
        state_manager: StateManager | None = None,
    ) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.agent_factory = agent_factory or DemoAgentFactory().create
        self.state_manager = state_manager or StateManager()

    def execute(
        self,
        workflow: Workflow,
        request: dict[str, Any],
        initial_state: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Run every node in a validated workflow until completion or abort."""
        errors = validate_graph(workflow)
        if errors:
            return ExecutionResult(
                task_id="",
                workflow=workflow.name,
                status="invalid",
                messages=(),
                artifacts={},
                state={"validation_errors": errors},
            )

        task_id = f"task-{uuid4().hex[:12]}"
        self.state_manager.start(task_id)
        artifacts_dir = self.artifacts_root / task_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        state = ExecutionState(
            task_id=task_id,
            request=request,
            artifacts_dir=artifacts_dir,
            data={"workflow": workflow.name, **dict(initial_state or {})},
        )

        status = "completed"
        for index, node in enumerate(workflow.nodes, start=1):
            agent = self.agent_factory(node)
            self.state_manager.record_node_start(task_id, node.value)
            message = agent.run(
                task_id=task_id,
                correlation_id=f"{index:02d}-{node.value}",
                payload={
                    "request": request,
                    "state": state.data,
                    "artifacts_dir": str(artifacts_dir),
                },
            )
            state.record(message)
            self.state_manager.record_message(task_id, node.value, message)
            if message.next_action is NextAction.ABORT:
                status = "aborted"
                break
            if message.next_action is NextAction.ESCALATE:
                status = "needs_attention"
                break

        artifacts = {
            "dataset_zip": str(state.data["dataset_zip"])
            for key in ("dataset_zip",)
            if key in state.data
        }
        return ExecutionResult(
            task_id=task_id,
            workflow=workflow.name,
            status=status,
            messages=tuple(state.history),
            artifacts=artifacts,
            state=state.data,
            progress=self.state_manager.get(task_id),
        )
