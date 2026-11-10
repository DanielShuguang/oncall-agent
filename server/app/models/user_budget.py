"""按用户的日预算覆盖（ADR-0026）。

表里只存「与全局默认不同」的用户：没有行就继承 `ONCALL_USER_DAILY_BUDGET_CNY`。
`daily_cents = 0` 是显式的「该用户不限」，与「没有行」不同——后者的默认值可能非零。

金额一律用「分」整数（R6）；改限额不重启，网关在模型调用前读一次（2s 缓存）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class UserBudget(Base):
    __tablename__ = "user_budgets"
    __table_args__ = (CheckConstraint("daily_cents >= 0", name="ck_user_budgets_daily_cents"),)

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: 日预算上限（分）；0 = 不限
    daily_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 最后一次修改人，便于对账；完整历史与工具覆盖一致，靠结构化日志
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
