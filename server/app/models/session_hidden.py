"""用户从会话列表里移除的会话（ADR-0041）。

会话仍由 `runs.session_id` 投影；这里只记录「这个用户不想在列表里再看到它」。
没有外键：run 与事件不因移除而删除，保留清理仍按 ADR-0021/0023 的保留期走。
没有额外索引：主键就是 `(user_id, session_id)`，列表投影按这两列做反连接。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class HiddenSession(Base):
    __tablename__ = "hidden_sessions"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hidden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
