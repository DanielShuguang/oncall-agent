"""run 正文按时间保留：`runs.content_pruned_at`（ADR-0023）

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-10

人工审过：
- 只加列 + 部分索引，不回填：`content_pruned_at IS NULL` 就是「正文还在」，
  现有的 run 全部保持原样，升级不动任何正文。
- 索引是**部分索引** `(finished_at) WHERE content_pruned_at IS NULL`，和服务对象
  `idx_runs_retention`（`WHERE events_pruned_at IS NULL`）分开：事件先清（保留天数
  要求 `run_content >= event`），清完的 run 会掉出事件索引，正文清理复用它会从最老的
  行开始扫、每轮越过整个历史。
- `input` 保持 NOT NULL：清理写空串而不是 NULL，避免为了「删内容」再改一次列约束；
  空串 + `content_pruned_at` 非空是唯一合法组合（空问题在接口层已被 400 拒绝）。
- 可回滚：downgrade 删索引与列，正文已被清空的 run 无法恢复（保留策略本来就是
  不可逆操作），其它字段不受影响。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("content_pruned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_runs_content_retention",
        "runs",
        ["finished_at"],
        postgresql_where=sa.text("content_pruned_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_runs_content_retention", table_name="runs")
    op.drop_column("runs", "content_pruned_at")
