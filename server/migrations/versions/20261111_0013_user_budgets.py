"""按用户的日预算覆盖：`user_budgets`（ADR-0026）

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-11

人工审过：
- 不建索引：表最多几百行（按需覆盖的用户），网关是整表读进 2s 缓存后按
  user_id 查内存字典；PK 用于管理接口的单条读写。加索引只会增加写放大。
- `daily_cents >= 0` 用 CHECK 兜底：0 是「显式不限」的合法值，负数没有语义；
  API 层也校验一次，但库是最后一道闸门。
- `updated_by` NOT NULL：预算是花钱的开关，必须能回答「谁改的」。
- 可回滚：downgrade 只删表；预算覆盖丢失后全部用户回到环境默认值（不会影响
  账本里已经累计的当日花费，账本在 Redis，按日过期）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_budgets",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("daily_cents", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("daily_cents >= 0", name="ck_user_budgets_daily_cents"),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_budgets"),
    )


def downgrade() -> None:
    op.drop_table("user_budgets")
