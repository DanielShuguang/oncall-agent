"""模拟业务域：资产（CMDB）与工单。

这些表是"可替换的真实系统"的本地替身：W2 seed 把演示数据落到这里，
W3 的 `query_cmdb` 已按 ADR-0034 真正查 `assets` 表（只查本人，身份由
ToolGuard 注入）。换成真实 CMDB 时替换 `app/tools/assets.py` 的仓储即可。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    location: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    warranty_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(16))


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(16))
    requester: Mapped[str] = mapped_column(String(64), nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(64))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
