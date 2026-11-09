"""工具运行时覆盖（W5 D22/D23）。

工具定义仍在代码里（`tools/builtin.py`）：schema、超时、是否写操作都要经过
code review 与测试，不能让管理页在线改出一个绕过治理的 schema。数据库只存
「与本环境默认值不同」的覆盖项：

- `enabled`：NULL 表示继承代码默认值；false 才是显式禁用
- `roles`：NULL 表示继承；`[]` 表示所有登录用户可用（与 `ToolSpec.roles=()` 同义）

只存覆盖而不是全量工具表，避免「代码加了工具但库里没同步」导致工具凭空消失。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class ToolSetting(Base):
    __tablename__ = "tool_settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    roles: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: 最后一次修改人；只留最新值，完整历史靠结构化日志
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
