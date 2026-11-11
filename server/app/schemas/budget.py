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


class ReservationStatsOut(BaseModel):
    """未结算预扣统计；`oldest_age_s` 为 None 表示没有可读时间戳的预扣。"""

    reserved_cents: int
    reservation_count: int
    stale_count: int
    stale_cents: int
    oldest_age_s: float | None = None


class GlobalBudgetUsageOut(ReservationStatsOut):
    #: 配置里的全局日上限（分）；0 表示不限
    limit_cents: int
    #: 含未结算预扣：这是账本口径，不是 model_calls 的实际成本
    spent_cents: int


class UserBudgetUsageOut(ReservationStatsOut):
    user_id: str
    spent_cents: int


class BudgetUsageResponse(BaseModel):
    #: 账本所属的 UTC 日（yyyy-mm-dd）
    day: str
    #: 超过多少秒仍未结算算「卡住」；目前固定 300 秒（ADR-0028）
    stale_after_s: float
    global_usage: GlobalBudgetUsageOut
    #: 只含有过预扣/花费的用户；管理页再与覆盖表做 union
    users: list[UserBudgetUsageOut]
