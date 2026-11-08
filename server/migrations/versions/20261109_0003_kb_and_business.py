"""知识库（pgvector + tsvector）与模拟业务表

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09

人工审过：
- 先 `CREATE EXTENSION IF NOT EXISTS vector`，否则 vector 类型与 HNSW 索引都会失败
- `kb_chunks.tsv` 由应用层分词后的 `tokens` 生成，不用 Postgres 默认中文分词
- HNSW 索引用 vector_cosine_ops；GIN 索引给 tsvector
- assets/tickets 是模拟 CMDB/工单系统，W3 让工具真正查表
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "kb_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'indexed'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_kb_documents"),
    )

    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("tokens", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            name="fk_kb_chunks_document_id_kb_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_kb_chunks"),
    )
    op.create_index("idx_chunks_doc", "kb_chunks", ["document_id", "ord"], unique=False)
    op.create_index(
        "idx_chunks_tsv",
        "kb_chunks",
        ["tsv"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "idx_chunks_vec",
        "kb_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("location", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("warranty_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("requester", sa.String(length=64), nullable=False),
        sa.Column("assignee", sa.String(length=64), nullable=True),
        sa.Column("asset_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_tickets_asset_id_assets"),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
    )


def downgrade() -> None:
    op.drop_table("tickets")
    op.drop_table("assets")
    op.drop_index("idx_chunks_vec", table_name="kb_chunks")
    op.drop_index("idx_chunks_tsv", table_name="kb_chunks")
    op.drop_index("idx_chunks_doc", table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
    # 不删 vector extension：同库可能有其他 schema 在用
