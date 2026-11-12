"""hidden_sessions：用户从会话列表移除的会话（ADR-0041）

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-12

软移除：只影响会话列表与标题搜索，不删 `runs`、事件、审批或标题行；保留清理
仍按 ADR-0021/0023 的时间口径执行。没有外键与额外索引：主键
`(user_id, session_id)` 足够列表投影做反连接。v1 没有恢复入口，行不自动清理。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hidden_sessions",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column(
            "hidden_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "session_id"),
    )


def downgrade() -> None:
    op.drop_table("hidden_sessions")
