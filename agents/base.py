"""Base agent - every agent is independent and speaks the Confidence Protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.core.protocol import AgentMessage


class BaseAgent(ABC):
    """All agents inherit from this. Agents NEVER call each other directly -
    they communicate via AgentMessage envelopes through the execution engine.
    Every emitted message is logged (feeds the Auditor's Decision Trail).
    """

    name: str = "base"

    @abstractmethod
    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Execute the agent's task and return a frozen-protocol message."""
        raise NotImplementedError
