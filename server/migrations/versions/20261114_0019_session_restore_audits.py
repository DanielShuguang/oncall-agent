"""已移除会话的恢复审计：`session_restore_audits`（ADR-0059）

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-14

人工审过：
- 按「一次恢复操作」落一行，而不是逐 session 一行：批量恢复的请求 id、实际
  恢复数、操作者与时间是一个整体，逐行会重复存 `user_id/restored_at`。
- `session_ids` 只存真正恢复的 id，`requested_count` 存去重后的请求数；
  `restored_count = jsonb_array_length(session_ids)` 用 CHECK 兜底，避免冗余
  计数与数组漂移。
- 两条索引：`(user_id, restored_at DESC)` 服务管理页按用户查最近恢复；
  `(restored_at)` 服务保留清理按时间扫。表只追加，索引写放大可接受。
- 无外键：会话与 run 仍可能被保留策略清正文/事件，但审计要独立留存。
- 保留期独立配置（默认 365 天），不复用正文保留期：恢复动作是治理审计，
  不是会话内容。
- 可回滚：downgrade 只删表；审计丢失不影响会话恢复本身。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_restore_audits",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "session_ids",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("restored_count", sa.Integer(), nullable=False),
        sa.Column(
            "restored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "restored_count = jsonb_array_length(session_ids)",
            name="ck_session_restore_audits_restored_count_matches_session_ids",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_restore_audits"),
    )
    op.create_index(
        "idx_session_restore_audits_user_time",
        "session_restore_audits",
        ["user_id", sa.text("restored_at DESC")],
    )
    op.create_index(
        "idx_session_restore_audits_time",
        "session_restore_audits",
        ["restored_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_session_restore_audits_time", table_name="session_restore_audits")
    op.drop_index("idx_session_restore_audits_user_time", table_name="session_restore_audits")
    op.drop_table("session_restore_audits")
