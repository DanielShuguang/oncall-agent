"""会话置顶/取消置顶的审计（ADR-0081）。

置顶是 per-user 的展示状态，管理/审计场景需要回答「谁在何时置顶或取消了这个
会话」。这里只记录显式 pin/unpin 操作：重复置顶、重复取消、隐藏/恢复会话导致
的置顶清理都不写审计，避免把无状态变化的请求放大成审计噪声。

没有外键：会话由 `runs.session_id` 投影，审计不随会话删除；由 RetentionSweeper
按 `ONCALL_SESSION_PIN_AUDIT_RETENTION_DAYS` 独立清理（ADR-0083）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class SessionPinAudit(Base):
    __tablename__ = "session_pin_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `pin` 或 `unpin`
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("action IN ('pin', 'unpin')", name="action_is_pin_or_unpin"),
        Index("idx_session_pin_audits_user_time", "user_id", text("created_at DESC")),
        Index("idx_session_pin_audits_session_time", "session_id", text("created_at DESC")),
        Index("idx_session_pin_audits_time", "created_at"),
    )
