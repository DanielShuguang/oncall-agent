"""成本看板与计量明细的响应模型（W4 D19）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CostItemOut(BaseModel):
    key: str
    calls: int
    token_in: int
    token_out: int
    cost_cents: int


class CostSummaryResponse(BaseModel):
    total_cents: int
    calls: int
    items: list[CostItemOut]


class ModelCallOut(BaseModel):
    step: str
    provider: str
    model: str
    token_in: int
    token_out: int
    cost_cents: int
    latency_ms: int
    first_token_ms: int | None = None
    status: str
    error: str | None = None
    created_at: datetime
