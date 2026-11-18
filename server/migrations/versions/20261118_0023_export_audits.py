"""export_audits：CSV 导出下载审计（ADR-0094）

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-18

记录成功返回的 CSV 导出：谁、什么资源、过滤条件、行数、是否截断。
审计写入失败时导出 503（fail closed）；当前不接入 RetentionSweeper。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_audits",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("resource", sa.String(length=32), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_export_audits_row_count_non_negative"),
        sa.CheckConstraint(
            "resource IN ("
            "'approvals', 'approval_stats', 'session_restores', "
            "'session_restore_stats', 'session_pins', 'session_pin_stats'"
            ")",
            name="ck_export_audits_resource",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_export_audits_time", "export_audits", ["created_at"], unique=False)
    op.create_index(
        "idx_export_audits_user_time",
        "export_audits",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_export_audits_resource_time",
        "export_audits",
        ["resource", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_export_audits_resource_time", table_name="export_audits")
    op.drop_index("idx_export_audits_user_time", table_name="export_audits")
    op.drop_index("idx_export_audits_time", table_name="export_audits")
    op.drop_table("export_audits")
