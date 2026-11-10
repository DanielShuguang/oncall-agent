"""数据保留清理（ADR-0021）

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-10

人工审过：
- `runs.events_pruned_at` 是「这场 run 的事件已被保留策略删除」的标记，不是新的事件。
  回放接口仍返回 200 + 空数组（run 存在），`GET /runs/{id}` 用这个字段告诉前端
  「不是没有事件，是过了保留期」，避免让空数组冒充一场真的没有事件的 run。
- 不删 `runs` 行，也不加级联：运行列表、成本口径与多轮上下文（ADR-0020）都依赖
  `runs.input/output`。只删 `run_events`，因此不需要新的外键或 CASCADE 调整。
- `idx_runs_finished_at` 只服务保留清理的候选扫描（`status IN (...) AND
  events_pruned_at IS NULL AND finished_at < cutoff`）。没有它每轮清理都要扫整表；
  该索引不参与任何在线请求路径，删除时也只影响清理任务。
- 回填：已有 run 全部 `events_pruned_at = NULL`，语义是「还没清过」；上线后第一轮
  清理会按 `finished_at` 处理过期的 run。事件表只增不删的旧行为到此为止。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("events_pruned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_runs_finished_at",
        "runs",
        ["finished_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_runs_finished_at", table_name="runs")
    op.drop_column("runs", "events_pruned_at")
