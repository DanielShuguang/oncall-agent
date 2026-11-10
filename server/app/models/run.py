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
    #: 事件已被保留策略清理的时间（ADR-0021）；有值时回放不可用，run 摘要仍保留
    events_pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 正文（`input`/`output`）已被保留策略清空的时间（ADR-0023）。有值时只剩摘要；
    #: 与按权限回收（ADR-0022）正交：那份是「当前看不到」，这份是「谁都不再留」
    content_pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 回答引用过的知识库文档 id（ADR-0022）。读回放时按**当前**可见性重新校验，
    #: 不能等到事件被清理后再算——那时 `message.completed` 里的引用已经没了
    cited_document_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )

    events: Mapped[list[RunEvent]] = relationship(back_populates="run", cascade="all, delete")

    __table_args__ = (
        # 幂等键按用户作用域：跨用户撞 key 不能互相回放（docs/02 §2.1）
        UniqueConstraint("user_id", "client_msg_id", name="uq_runs_user_client_msg"),
        Index("idx_runs_user_time", "user_id", text("started_at DESC")),
        # 多轮上下文按会话取最近几轮（ADR-0020）；(user_id, started_at) 的前缀
        # 不支持 session_id 过滤，会话一多就要读该用户全部 run
        Index("idx_runs_user_session_time", "user_id", "session_id", text("started_at DESC")),
        # 保留清理按「结束时间早于阈值」扫候选（ADR-0021）。用部分索引只索引
        # events_pruned_at IS NULL 的 run：普通 finished_at 索引会从最老的行开始扫，
        # 而最老的行恰好全是已清理的，每轮都要越过整个历史才能找到候选
        Index(
            "idx_runs_retention",
            "finished_at",
            postgresql_where=text("events_pruned_at IS NULL"),
        ),
        # 正文清理单独一个部分索引（ADR-0023）：事件先清，清完的行会掉出
        # `idx_runs_retention`，正文清理不能复用那个索引，否则每轮都要全表扫起
        Index(
            "idx_runs_content_retention",
            "finished_at",
            postgresql_where=text("content_pruned_at IS NULL"),
        ),
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
