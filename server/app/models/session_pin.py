"""会话置顶表（ADR-0069）。

一个用户可以把会话固定在列表顶部；置顶是 per-user 的，不影响其他用户。
没有外键与额外索引：主键 `(user_id, session_id)` 足够列表投影做左连接，
隐藏会话时同事务删除置顶行。`pinned_at` 只用于审计式排查，不参与排序——
置顶组内仍按会话最近活动排序，避免「越早置顶越靠前」压住活跃会话。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PinnedSession(Base):
    __tablename__ = "pinned_sessions"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
