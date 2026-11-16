"""session_pin_audits：会话置顶/取消置顶的审计（ADR-0081）

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-16

只记录显式状态变化：重复置顶/重复取消、隐藏会话带来的置顶清理不写审计。
没有外键；审计暂随数据库保留，不接入 RetentionSweeper（待定）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_pin_audits",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('pin', 'unpin')", name="ck_session_pin_audits_action_is_pin_or_unpin"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_session_pin_audits_user_time",
        "session_pin_audits",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_session_pin_audits_session_time",
        "session_pin_audits",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_session_pin_audits_time",
        "session_pin_audits",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_session_pin_audits_time", table_name="session_pin_audits")
    op.drop_index("idx_session_pin_audits_session_time", table_name="session_pin_audits")
    op.drop_index("idx_session_pin_audits_user_time", table_name="session_pin_audits")
    op.drop_table("session_pin_audits")
