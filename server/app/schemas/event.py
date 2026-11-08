"""事件契约（前后端唯一真相）。

新增事件类型只能追加，不能改名；payload 只能加可选字段。
前端遇到未知 type 必须忽略而不是崩溃，见 docs/03-api-contract.md。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_RESOLVED = "approval.resolved"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    HEARTBEAT = "heartbeat"


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RunEvent(BaseModel):
    """一条运行事件。seq 在单个 run 内从 1 严格递增。"""

    seq: int
    run_id: str
    type: EventType
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    """引用溯源信息，前端据此跳原文。"""

    chunk_id: int
    document_id: str
    ord: int
    title: str
    heading: str | None = None
    snippet: str
    page: int | None = None


class ToolStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    DENIED = "denied"
    REQUIRES_APPROVAL = "requires_approval"


class StepInfo(BaseModel):
    node: str
    title: str
    duration_ms: int | None = None
