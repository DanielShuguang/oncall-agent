"""恢复审计按 session 反查：`session_ids` 的 GIN 索引（ADR-0061）

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-14

人工审过：
- 管理端要回答「这个会话被谁恢复过」，查询是 `session_ids @> '["sess_x"]'`；
  没有索引时 365 天审计表只能全表扫。
- 用 `jsonb_path_ops` 而不是默认 `jsonb_ops`：只支持 `@>`/`?` 等路径操作，
  索引更小，正好覆盖本查询；不改变任何行。
- 表已有 `(user_id, restored_at DESC)` 与 `(restored_at)` 两条 B-tree；
  本索引只服务 session 包含查询，与分页/清理索引并存。
- 可回滚：downgrade 只删索引，不触碰审计数据。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_session_restore_audits_sessions",
        "session_restore_audits",
        ["session_ids"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"session_ids": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "idx_session_restore_audits_sessions",
        table_name="session_restore_audits",
    )
