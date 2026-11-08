"""runs 与 run_events：事件落库，支持 Last-Event-ID 续传

Revision ID: 0001
Revises:
Create Date: 2026-11-08

人工审过：索引名与 docs/02-data-model.md 一致；`runs` 没有 created_at，
时间基准是 started_at；`run_events` 只追加，不设 updated_at。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_msg_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("step_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_steps", sa.Integer(), server_default=sa.text("12"), nullable=False),
        sa.Column("token_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("token_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
        sa.UniqueConstraint("client_msg_id", name="uq_runs_client_msg_id"),
    )
    op.create_index(
        "idx_runs_user_time",
        "runs",
        ["user_id", sa.text("started_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_runs_status",
        "runs",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status IN ('running','awaiting_approval')"),
    )

    op.create_table(
        "run_events",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_run_events_run_id_runs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "seq", name="pk_run_events"),
    )
    op.create_index("idx_events_type", "run_events", ["run_id", "type"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_events_type", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("idx_runs_status", table_name="runs")
    op.drop_index("idx_runs_user_time", table_name="runs")
    op.drop_table("runs")
