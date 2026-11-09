"""审批接口的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
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


class ApprovalResolveResponse(BaseModel):
    approval: ApprovalOut
    run_id: str
    run_status: str | None = None
