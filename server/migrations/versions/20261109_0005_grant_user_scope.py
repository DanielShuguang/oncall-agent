"""审批会话授权按用户隔离

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09

问题：`approval_grants` 主键是 (session_id, tool_name)，而 session_id 由客户端
传入。复用别人的 session_id 就能继承 scope=session 的授权，等于绕过审批开单。
修复：主键改成 (user_id, session_id, tool_name)，user_id 取审批记录的发起人。

人工审过：
- 先加列并回填（回填自 approvals.requested_by），再收紧 NOT NULL 与主键
- 回填不到的历史行置空串，效果是授权失效（安全方向），不会误放行
- downgrade 先按 session/tool 去重，否则旧主键会因多用户授权而冲突
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approval_grants",
        sa.Column(
            "user_id",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.execute(
        """
        UPDATE approval_grants AS g
        SET user_id = COALESCE(
            (
                SELECT a.requested_by
                FROM approvals AS a
                WHERE a.session_id = g.session_id
                  AND a.tool_name = g.tool_name
                  AND a.status = 'approved'
                ORDER BY a.resolved_at DESC NULLS LAST
                LIMIT 1
            ),
            ''
        )
        WHERE g.user_id = ''
        """
    )
    op.alter_column("approval_grants", "user_id", server_default=None)
    op.drop_constraint("pk_approval_grants", "approval_grants", type_="primary")
    op.create_primary_key(
        "pk_approval_grants",
        "approval_grants",
        ["user_id", "session_id", "tool_name"],
    )


def downgrade() -> None:
    op.drop_constraint("pk_approval_grants", "approval_grants", type_="primary")
    # 旧主键不允许同一 session/tool 有多用户授权，保留任意一条即可
    op.execute(
        """
        DELETE FROM approval_grants AS a
        USING approval_grants AS b
        WHERE a.ctid < b.ctid
          AND a.session_id = b.session_id
          AND a.tool_name = b.tool_name
        """
    )
    op.create_primary_key(
        "pk_approval_grants",
        "approval_grants",
        ["session_id", "tool_name"],
    )
    op.drop_column("approval_grants", "user_id")
