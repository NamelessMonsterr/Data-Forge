"""Agent Communication Protocol - FROZEN.

Every agent output MUST use the AgentMessage envelope. `next_action` is a strict
enum (continue | retry | escalate | abort) - no free-form values, no string parsing.
Large artifacts are passed by reference (`payload_ref` -> object storage), never inline.
Every message is versioned and logged (feeds the Auditor's Decision Trail).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "1.0"


class NextAction(str, Enum):
    """The ONLY legal next_action values. Frozen."""

    CONTINUE = "continue"
    RETRY = "retry"
    ESCALATE = "escalate"
    ABORT = "abort"


class MessageStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class AgentMessage(BaseModel):
    """Frozen Confidence Protocol envelope.

    Example:
        {
          "agent": "Validator",
          "task_id": "task-91",
          "correlation_id": "node-validator-1",
          "status": "PASS",
          "confidence": 0.97,
          "reason": "Quality exceeded threshold.",
          "next_action": "continue"
        }
    """

    agent: str
    task_id: str
    correlation_id: str = Field(
        description="Ties this message to a specific execution-graph node."
    )
    status: MessageStatus
    result: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    next_action: NextAction
    payload_ref: Optional[str] = Field(
        default=None,
        description="Object-storage reference for large artifacts (datasets, reports).",
    )
    version: str = PROTOCOL_VERSION
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
