"""审批接口的请求/响应模型。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ApprovalResolveRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=500)
    scope: Literal["once", "session"] = "once"


class ApprovalOut(BaseModel):
    approval_id: str
    run_id: str
    call_id: str
    tool: str
    args: dict[str, Any]
    risk_level: str
    status: str
    requested_by: str
    resolved_by: str | None = None
    reason: str | None = None
    scope: str
    expires_at: datetime
    created_at: datetime
    resolved_at: datetime | None = None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalOut]
    #: 当前页取满时返回的 keyset 游标；没有更多为 None（ADR-0052）
    next_cursor: str | None = None


class ApprovalDayStatsOut(BaseModel):
    """按 UTC 日期聚合的已决议趋势（ADR-0050）；只含窗口内有决议的日期。"""

    day: date
    decided_count: int
    avg_wait_ms: int | None = None


class ApprovalGroupStatsOut(BaseModel):
    """窗口内某一维度的已决议数量与等待（ADR-0051）。"""

    key: str
    decided_count: int
    avg_wait_ms: int | None = None
    max_wait_ms: int | None = None


class ApprovalStatsResponse(BaseModel):
    """审批人视角的积压、窗口内等待、按日趋势与分组（ADR-0048/0050/0051）。"""

    days: int
    pending_count: int
    oldest_pending_age_s: int | None = None
    decided_count: int
    avg_wait_ms: int | None = None
    max_wait_ms: int | None = None
    daily: list[ApprovalDayStatsOut] = Field(default_factory=list)
    groups: list[ApprovalGroupStatsOut] = Field(default_factory=list)
    groups_truncated: bool = False


class ApprovalResolveResponse(BaseModel):
    approval: ApprovalOut
    run_id: str
    run_status: str | None = None
