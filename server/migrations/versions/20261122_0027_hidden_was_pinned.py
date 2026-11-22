"""hidden_sessions：记录移除时是否置顶（ADR-0108）

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-22

隐藏会话时原本会直接删除 `pinned_sessions` 行，恢复后无法知道它是否曾置顶。
新增非空布尔列 `was_pinned`，默认 false；旧行按未置顶处理，不回填。
恢复时按当前置顶容量尽力恢复，超出容量则恢复为未置顶。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hidden_sessions",
        sa.Column(
            "was_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("hidden_sessions", "was_pinned")
