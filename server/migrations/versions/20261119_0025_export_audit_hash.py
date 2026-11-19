"""export_audits：记录导出 CSV 的 SHA-256（ADR-0097）

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-19

给每次导出审计增加 `content_sha256`，用于离线核对下载文件是否与当时服务端生成的
内容一致。旧记录没有哈希，保持 NULL；新导出由 API 计算后写入，不做历史回填。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "export_audits",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("export_audits", "content_sha256")
