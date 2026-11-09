"""运行与事件表。

字段定义见 docs/02-data-model.md，迁移见 `migrations/versions/0001_runs_and_events.py`。
`runs` 的汇总字段是事件投影的结果（见 `core/store.py`），不要在其他地方直接改。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_msg_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    input: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str | None] = mapped_column(Text)
    step_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    max_steps: Mapped[int] = mapped_column(
        Integer, default=12, server_default=text("12"), nullable=False
    )
    token_in: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    token_out: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    cost_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    #: 失败归因大类（model/tool/approval/limit/internal），由 run.failed 投影写入
    failure_category: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[RunEvent]] = relationship(back_populates="run", cascade="all, delete")

    __table_args__ = (
        # 幂等键按用户作用域：跨用户撞 key 不能互相回放（docs/02 §2.1）
        UniqueConstraint("user_id", "client_msg_id", name="uq_runs_user_client_msg"),
        Index("idx_runs_user_time", "user_id", text("started_at DESC")),
        Index(
            "idx_runs_status",
            "status",
            postgresql_where=text("status IN ('running','awaiting_approval')"),
        ),
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="events")

    __table_args__ = (Index("idx_events_type", "run_id", "type"),)
