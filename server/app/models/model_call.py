"""模型调用计量表（W4 D18）。

一行 = 一次真实 provider 调用（含失败尝试）。`runs` 的 token/cost 汇总由
`gateway.meter` 在写这一行时**增量更新**，而不是等 `run.completed` 再算，
这样失败/中断的 run 也能满足 `runs.token_in == sum(model_calls.token_in)`。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    #: 节点名（classify / plan / answer），用于回答「贵在哪一步」
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    #: cloud | local
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    token_in: Mapped[int] = mapped_column(Integer, nullable=False)
    token_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    #: ok | error | fallback
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        # 成本看板按时间范围聚合；run 详情按 run_id 回查
        Index("idx_model_calls_day", "created_at"),
        Index("idx_model_calls_run", "run_id"),
    )
