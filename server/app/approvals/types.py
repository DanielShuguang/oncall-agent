"""审批域的类型与协议。

runtime 只依赖这里的 `ApprovalRecorder`，不碰 SQL（R4 的同一条精神：
业务层通过协议访问存储）。具体实现在 `store.py` / `service.py`。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Protocol


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
class ApprovalDayStats:
    """按 UTC 日期聚合的已决议数量与平均等待（ADR-0050）。

    只包含窗口内真正有决议的日期，不做零填充：调用方按返回的日期画趋势即可，
    避免为了补零把窗口边界与 `since` 的滚动窗口语义搅在一起。
    """

    day: date
    decided_count: int
    avg_wait_ms: int | None


#: 统计分组维度；None 表示只要窗口汇总（ADR-0051）
ApprovalGroupBy = Literal["tool", "approver"]

#: 分组结果最多返回多少行，避免审批人/工具很多时把响应撑大
MAX_STATS_GROUPS = 20


@dataclass(frozen=True)
class ApprovalGroupStats:
    """窗口内某一维度的已决议数量与等待（ADR-0051）。

    只聚合已决议（approved/rejected）的审批：待办还没有审批人归属，不能按
    `resolved_by` 分组；按工具分组也不混入待办，保证各分组之和等于
    `decided_count`。
    """

    key: str
    decided_count: int
    avg_wait_ms: int | None
    max_wait_ms: int | None


@dataclass(frozen=True)
class ApprovalStats:
    """审批积压与等待统计（ADR-0048 / ADR-0050）。

    `oldest_pending_age_s` 是当前待办的「已等秒数」，用于发现卡住的单；
    `avg_wait_ms` / `max_wait_ms` 只统计窗口内已决议（approved/rejected）的审批，
    不把过期（expired）算成人工等待，避免把 TTL 时长混进流程指标。
    `daily` 是同一窗口内按 UTC 日期分桶的稀疏趋势（ADR-0050）。
    """

    pending_count: int
    oldest_pending_age_s: int | None
    decided_count: int
    avg_wait_ms: int | None
    max_wait_ms: int | None
    daily: tuple[ApprovalDayStats, ...] = ()
    groups: tuple[ApprovalGroupStats, ...] = ()
    groups_truncated: bool = False


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
