"""run 引用快照：回答引用了哪些知识库文档（ADR-0022）

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-10

人工审过：
- `runs.cited_document_ids` 是 `message.completed.citations[].document_id` 的投影，
  不是新事件。它必须**落在 runs 上**而不是读事件：事件默认 180 天后会被整场清理
  （ADR-0021），而 `runs.output` 还留着；如果引用快照跟着事件一起消失，清理过的
  run 就再也没法按当前可见性回收内容了。
- 存量回填：从 `message.completed` 事件里抽 `document_id`（`jsonb_path_query` 在
  lax 模式下对缺失/非数组路径返回空集，不会因为脏 payload 让升级失败；只取 JSON
  字符串，和运行时投影 `_cited_document_ids` 的口径一致）。只回填一次；已经清理过
  事件的 run 没有引用可抽，保持空数组 → 这些 run 的回答不会因为权限变更被隐藏
  （迁移前就存在的局限，写在 ADR-0022 的「代价」里）。回填是全表 UPDATE，
  大库应在维护窗口执行。
- 不加索引：唯一读法是按主键取一场 run 的引用，走的还是 `runs` 主键。
- 可回滚：downgrade 只删列，不影响事件与其它汇总字段。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 从 message.completed 的 citations 数组里取 document_id。
# `jsonb_path_query` 用 lax 模式：payload 里没有 citations、citations 不是数组、
# 元素不是对象时都返回空集，而不是抛错。
_BACKFILL = """
UPDATE runs AS r
SET cited_document_ids = COALESCE(
    (
        SELECT jsonb_agg(DISTINCT doc_id)
        FROM run_events AS e
        CROSS JOIN LATERAL jsonb_path_query(
            e.payload, '$.citations[*].document_id'
        ) AS doc_id
        WHERE e.run_id = r.id
          AND e.type = 'message.completed'
          AND jsonb_typeof(doc_id) = 'string'
    ),
    '[]'::jsonb
)
"""


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "cited_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.drop_column("runs", "cited_document_ids")
