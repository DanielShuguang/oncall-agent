"""approvals 已办按决议时间翻页索引（ADR-0053）

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-13

已办列表从 `(expires_at, created_at, id)` 升序改为 `(resolved_at, id)` 倒序：
最近决议的记录在最前。`idx_approvals_pending` 只覆盖待办的到期排序，无法服务
已办的反向扫描，因此补一个部分索引；`resolved_at IS NULL` 的 pending 行不进入
索引，写入成本与原表相同。索引列用默认升序即可——PostgreSQL 可以反向扫描来
满足两列同时 DESC 的排序与 keyset 条件。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_approvals_resolved",
        "approvals",
        ["status", "resolved_at", "id"],
        postgresql_where=sa.text("resolved_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_approvals_resolved", table_name="approvals")
