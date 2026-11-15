"""pinned_sessions：用户置顶的会话（ADR-0069）

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-15

置顶是 per-user 展示状态：主键 `(user_id, session_id)`，无外键与额外索引。
`pinned_at` 仅记录置顶时间，不参与排序；列表置顶组内仍按会话最近活动倒序。
隐藏会话时同事务删除置顶行，恢复已移除会话也不会自动恢复置顶。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pinned_sessions",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "session_id"),
    )


def downgrade() -> None:
    op.drop_table("pinned_sessions")
