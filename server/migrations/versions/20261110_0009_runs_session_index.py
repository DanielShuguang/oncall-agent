"""会话历史的索引（ADR-0020）

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10

人工审过：
- 多轮上下文每轮都会查「同一用户 + 同一会话最近 N 条有回答的 run」，
  走 `(user_id, session_id, started_at DESC)` 索引后是索引区间扫描 + 取前 N 行；
  只建 `user_id` 前缀的 `idx_runs_user_time` 需要把该用户所有 run 都读出来再过滤
- 仍保留 `idx_runs_user_time`：会话历史按 (session, time) 查，运行列表按 (user, time) 查，
  两者不是同一个前缀，删旧的会让 `/runs` 退化成排序整表
- 索引不含 `output`：`output` 是 Text，加进索引会让每条事件写入都维护一份回答正文；
  这里只按「有回答」过滤，读回正文本来就要回表
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_runs_user_session_time",
        "runs",
        ["user_id", "session_id", sa.text("started_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_runs_user_session_time", table_name="runs")
