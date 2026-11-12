"""session_titles：用户自定义会话标题（ADR-0040）

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12

会话仍是 `runs.session_id` 的投影；这张表只存改过的显示标题，没有外键。
没有额外索引：主键就是 `(user_id, session_id)`，列表投影按这两个列 join。
保留清理不会删这张表：标题行可能比 run 活得久，量小暂不处理（ADR-0040 待定）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_titles",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "session_id"),
    )


def downgrade() -> None:
    op.drop_table("session_titles")
