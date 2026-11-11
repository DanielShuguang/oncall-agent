"""回答引用快照：`runs.citations`（ADR-0031）

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12

人工审过：
- 存完整引用快照（chunk_id/document_id/ord/title/heading/snippet/page），而不是
  只存文档 id：历史会话要能还原角标与预览，事件被 ADR-0021 清理后不能再从
  `message.completed` 里取。
- `NOT NULL DEFAULT '[]'`：空数组表示「这轮没有引用」，与「字段不存在」区分；
  旧 run 自动得到 `[]`，不做回填。
- 不建索引：只按 run 主键整行读取，没有按引用内容检索的需求。
- 与 ADR-0023 的正文清理同一时点清空：引用片段属于回答内容，正文删掉后不能
  只留片段。`cited_document_ids` 不清（权限回收还要用，ADR-0022）。
- 可回滚：downgrade 只删列；旧代码不再读这份快照，事件还在时可从事件重建。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "citations",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "citations")
