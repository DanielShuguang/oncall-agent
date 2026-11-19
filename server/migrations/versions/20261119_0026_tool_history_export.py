"""export_audits：资源枚举支持工具变更历史导出（ADR-0099）

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-19

工具配置变更历史也可以导出为 CSV；导出行为同样写 `tool_setting_history`
记录。这里只扩展 CHECK，不改字段或索引。

downgrade 先删除 `resource=tool_setting_history` 的审计行：旧 CHECK 不允许该资源，
保留这些行会让 0025 的约束无法建立；降级即放弃「工具历史导出」能力。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCES_7 = (
    "resource IN ("
    "'approvals', 'approval_stats', 'session_restores', "
    "'session_restore_stats', 'session_pins', 'session_pin_stats', 'export_audits'"
    ")"
)
_RESOURCES_8 = (
    "resource IN ("
    "'approvals', 'approval_stats', 'session_restores', "
    "'session_restore_stats', 'session_pins', 'session_pin_stats', "
    "'export_audits', 'tool_setting_history'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_export_audits_resource", "export_audits", type_="check")
    op.create_check_constraint("ck_export_audits_resource", "export_audits", _RESOURCES_8)


def downgrade() -> None:
    op.execute("DELETE FROM export_audits WHERE resource = 'tool_setting_history'")
    op.drop_constraint("ck_export_audits_resource", "export_audits", type_="check")
    op.create_check_constraint("ck_export_audits_resource", "export_audits", _RESOURCES_7)
