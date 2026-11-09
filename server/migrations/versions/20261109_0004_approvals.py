"""审批表与会话级授权

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09

人工审过：
- `approvals.state` 是挂起瞬间的 AgentState 快照（JSONB），审批通过后从这里恢复
- 待办唯一索引是**部分索引**：只约束 status='pending'，历史决议可以保留多条
- `approval_grants` 让 resolve 的 scope=session 有落点；过期后自然回到逐次审批
- run 删除时审批级联删除（审计已进 run_events，业务表不保留孤儿）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "scope",
            sa.String(length=16),
            server_default=sa.text("'once'"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_approvals_run_id_runs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
    )
    op.create_index(
        "uq_approval_pending",
        "approvals",
        ["run_id", "tool_name"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_approvals_pending", "approvals", ["status", "expires_at"], unique=False)

    op.create_table(
        "approval_grants",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("session_id", "tool_name", name="pk_approval_grants"),
    )


def downgrade() -> None:
    op.drop_table("approval_grants")
    op.drop_index("idx_approvals_pending", table_name="approvals")
    op.drop_index("uq_approval_pending", table_name="approvals")
    op.drop_table("approvals")
