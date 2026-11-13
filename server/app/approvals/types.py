"""审批域的类型与协议。

runtime 只依赖这里的 `ApprovalRecorder`，不碰 SQL（R4 的同一条精神：
业务层通过协议访问存储）。具体实现在 `store.py` / `service.py`。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class ApprovalError(Exception):
    """审批域错误的基类，API 层统一翻译成 4xx。"""


class ApprovalNotFound(ApprovalError):
    pass


class ApprovalForbidden(ApprovalError):
    pass


class ApprovalScopeUnsupported(ApprovalError):
    pass


class ApprovalNotReady(ApprovalError):
    """run 还没进入 awaiting_approval（approval.required 尚未落库）。"""


@dataclass(frozen=True)
class ApprovalRequestInfo:
    """提交审批后回给 runtime 的最小信息。"""

    approval_id: str
    expires_at: datetime


@dataclass(frozen=True)
class ApprovalStats:
    """审批积压与等待统计（ADR-0048）。

    `oldest_pending_age_s` 是当前待办的「已等秒数」，用于发现卡住的单；
    `avg_wait_ms` / `max_wait_ms` 只统计窗口内已决议（approved/rejected）的审批，
    不把过期（expired）算成人工等待，避免把 TTL 时长混进流程指标。
    """

    pending_count: int
    oldest_pending_age_s: int | None
    decided_count: int
    avg_wait_ms: int | None
    max_wait_ms: int | None


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    run_id: str
    call_id: str
    tool_name: str
    args: dict[str, Any]
    risk_level: str
    status: str
    requested_by: str
    expires_at: datetime
    created_at: datetime
    resolved_by: str | None = None
    reason: str | None = None
    scope: str = "once"
    session_id: str | None = None
    resolved_at: datetime | None = None
    #: 挂起瞬间的 AgentState 快照；审批通过后从这里恢复 act，而不是重跑整条链
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"


class ApprovalRecorder(Protocol):
    """runtime 视角的审批能力：提交审批 + 查询会话级授权。"""

    async def request(
        self,
        *,
        run_id: str,
        call_id: str,
        session_id: str | None,
        tool_name: str,
        args: Mapping[str, Any],
        risk_level: str,
        state: Mapping[str, Any],
        requested_by: str,
    ) -> ApprovalRequestInfo: ...

    async def is_granted(self, *, user_id: str, session_id: str | None, tool_name: str) -> bool: ...
