"""工具运行时覆盖（W5 D22/D23）

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09

人工审过：
- 不建 `tools` 全量表：工具定义在代码里，schema / is_write / timeout 必须走
  code review；库里只存与本环境默认值不同的覆盖（enabled / roles）
- `enabled` 与 `roles` 都允许 NULL，分别表示继承代码默认值；`roles=[]` 表示
  所有登录用户可用
- `updated_by` 只留最后修改人，完整历史看结构化日志（当前不建审计表）
- 不建外键（没有 tools 表）；删除工具时残留的覆盖行会在读取时被忽略
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_settings",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name", name="pk_tool_settings"),
    )


def downgrade() -> None:
    op.drop_table("tool_settings")
