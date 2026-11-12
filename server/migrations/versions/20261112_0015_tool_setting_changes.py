"""工具配置变更审计：`tool_setting_changes`（ADR-0037）

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12

人工审过：
- 只追加、不修改、不删除：这是治理证据，不是缓存。`before` / `after` 存完整的
  覆盖快照（enabled + roles），NULL 表示「没有覆盖、走代码默认」，因此能还原
  「从禁用改回继承」这类动作。
- 无变化不落行：管理页重复保存同一份配置不应产生噪声。
- 只记录管理 API 的写入（source=tool / matrix）；进程内直接调 `set_override`
  的系统/测试写入不记 `changed_by`，没有可信身份可写。
- 索引 `(tool_name, changed_at DESC)`：管理页只按工具查最近 N 条；没有按时间
  全表扫描的管理接口，暂不建全局时间索引。
- 不设保留期：与审批决议行一样属于长期审计证据；增长量与管理员操作次数同阶，
  远小于 run 事件。需要清理时另立 ADR。
- downgrade 直接删表：历史仅在审计页展示，监控/告警不依赖它。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_setting_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("before", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tool_setting_changes_tool_time",
        "tool_setting_changes",
        ["tool_name", sa.text("changed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_tool_setting_changes_tool_time", table_name="tool_setting_changes")
    op.drop_table("tool_setting_changes")
