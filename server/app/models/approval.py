"""审批表：待办、决议与参数快照（docs/02 §2.3）。

`state` 是挂起瞬间的 AgentState 快照。审批通过后 runtime 从快照恢复 act，
而不是重跑整条链 —— 否则用户等待审批期间改的知识库/工具会改变执行结果，
审批人看到的参数也就不可信了。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'"), nullable=False
    )
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(
        String(16), default="once", server_default=text("'once'"), nullable=False
    )
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # 同一 run 同一工具只允许一条待办：重复调用应命中已有审批，不能生成两张卡
        Index(
            "uq_approval_pending",
            "run_id",
            "tool_name",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("idx_approvals_pending", "status", "expires_at"),
        # 已办按决议时间倒序翻页（ADR-0053）；部分索引只收有决议的行，
        # pending 不占空间，查询里的 `resolved_at IS NOT NULL` 可命中它。
        Index(
            "idx_approvals_resolved",
            "status",
            "resolved_at",
            "id",
            postgresql_where=text("resolved_at IS NOT NULL"),
        ),
    )


class ApprovalGrant(Base):
    """会话级授权：resolve 时选 scope=session，本会话再调同类工具不再询问。

    `user_id` 必须在主键里：session_id 由客户端传入，只按 (session, tool) 授权
    会让别人复用同一个 session_id 继承授权（越权开单）。
    只存"已授权"，不存业务参数；授权过期后自然回到逐次审批。
    """

    __tablename__ = "approval_grants"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
