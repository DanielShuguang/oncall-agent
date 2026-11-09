"""模型调用计量表与失败归因

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09

人工审过：
- `model_calls` 一行对应一次真实 provider 调用（失败尝试也留痕，token 记 0）
- `runs` 的 token/cost 由 gateway 在写计量行时增量更新，保证失败/中断的 run
  也满足 `runs.token_in == sum(model_calls.token_in)`（docs/02 §3）
- `failure_category` 只做归因大类，不替代 `error_code`；旧 run 保持 NULL
- `model_calls.run_id` 级联删除：run 是聚合根，事件表已保留审计
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("token_in", sa.Integer(), nullable=False),
        sa.Column("token_out", sa.Integer(), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_model_calls_run_id_runs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_calls"),
    )
    op.create_index("idx_model_calls_day", "model_calls", ["created_at"], unique=False)
    op.create_index("idx_model_calls_run", "model_calls", ["run_id"], unique=False)

    op.add_column(
        "runs",
        sa.Column("failure_category", sa.String(length=24), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "failure_category")
    op.drop_index("idx_model_calls_run", table_name="model_calls")
    op.drop_index("idx_model_calls_day", table_name="model_calls")
    op.drop_table("model_calls")
