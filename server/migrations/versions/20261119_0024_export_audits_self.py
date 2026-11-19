"""export_audits：资源枚举支持审计日志自身导出（ADR-0096）

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-19

导出审计列表也可以导出为 CSV；该导出本身同样写一条 `resource=export_audits`
记录，否则治理证据会缺失。这里只扩展 CHECK，不改字段或索引。

downgrade 先删除 `resource=export_audits` 的审计行：旧 CHECK 只允许 6 种资源，
保留这些行会让 0023 的约束无法建立；降级即放弃「导出审计自身导出」能力，这些
行对应的动作在旧版本也不存在。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCES_6 = (
    "resource IN ("
    "'approvals', 'approval_stats', 'session_restores', "
    "'session_restore_stats', 'session_pins', 'session_pin_stats'"
    ")"
)
_RESOURCES_7 = (
    "resource IN ("
    "'approvals', 'approval_stats', 'session_restores', "
    "'session_restore_stats', 'session_pins', 'session_pin_stats', 'export_audits'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_export_audits_resource", "export_audits", type_="check")
    op.create_check_constraint("ck_export_audits_resource", "export_audits", _RESOURCES_7)


def downgrade() -> None:
    op.execute("DELETE FROM export_audits WHERE resource = 'export_audits'")
    op.drop_constraint("ck_export_audits_resource", "export_audits", type_="check")
    op.create_check_constraint("ck_export_audits_resource", "export_audits", _RESOURCES_6)
