"""会话自定义标题（ADR-0040）。

会话本身没有独立实体，仍由 `runs.session_id` 投影；这里只存用户改过的显示标题。
没有外键：会话什么时候消失取决于 `runs`，这张表只是旁挂的展示信息，run 被保留清理后
标题行可能暂时成为孤儿（量小，暂不做清理任务）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class SessionTitle(Base):
    __tablename__ = "session_titles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: 只存用户自定义标题；没有这一行时回落到首条非空 input
    title: Mapped[str] = mapped_column(String(60), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
