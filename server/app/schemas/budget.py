"""按用户日预算的请求/响应模型（docs/03 §5「按用户日预算」，ADR-0026）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

#: 上限 1 万元/天。再高的额度应该走采购/合同，而不是让管理页手滑多打几个零
MAX_DAILY_CENTS = 1_000_000


class UserBudgetOut(BaseModel):
    user_id: str
    #: 日上限（分）；0 表示该用户不限（与「没有覆盖」不同）
    daily_cents: int
    updated_by: str
    updated_at: datetime | None = None


class UserBudgetListResponse(BaseModel):
    #: 没有覆盖的用户按这个值（0 = 不限）
    default_cents: int
    overrides: list[UserBudgetOut]


class UserBudgetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 日上限（分）；0 是显式的不限
    daily_cents: int = Field(ge=0, le=MAX_DAILY_CENTS)
