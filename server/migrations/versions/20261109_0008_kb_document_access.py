"""知识库文档级可见性（ADR-0019）

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09

人工审过：
- 存量文档全部落成 `public`（server_default）——升级行为是「可见性不变」，
  而不是把旧文档默认锁死；需要收紧就逐篇 PATCH
- `allowed_roles` 用 `varchar(32)[]` + `&&`（数组重叠）过滤：一次索引扫描后
  在 WHERE 里丢弃不可见行，不会让受限文档占掉 `LIMIT` 名额
- CHECK 把两种解释写成互斥：`public` 必须没有角色，`roles` 必须至少一个角色。
  没有这条约束，「public 但有角色」在 SQL 与 Python 里会有两种读法
- 不加 `(visibility, allowed_roles)` 索引：v1 文档量在万级以内，
  且可见性过滤是切片的附加条件，先看 HNSW/GIN 的执行计划再决定
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kb_documents",
        sa.Column(
            "visibility",
            sa.String(length=16),
            server_default=sa.text("'public'"),
            nullable=False,
        ),
    )
    op.add_column(
        "kb_documents",
        sa.Column(
            "allowed_roles",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    # 命名约定 ck_%(table_name)s_%(constraint_name)s：这里只给短名，
    # 最终约束是 ck_kb_documents_access（与模型一致；给全名会变成双前缀）
    op.create_check_constraint(
        "access",
        "kb_documents",
        "(visibility = 'public' AND cardinality(allowed_roles) = 0)"
        " OR (visibility = 'roles' AND cardinality(allowed_roles) > 0)",
    )


def downgrade() -> None:
    # 与 upgrade 对称：同样只给短名，约定会补成 ck_kb_documents_access
    op.drop_constraint("access", "kb_documents", type_="check")
    op.drop_column("kb_documents", "allowed_roles")
    op.drop_column("kb_documents", "visibility")
