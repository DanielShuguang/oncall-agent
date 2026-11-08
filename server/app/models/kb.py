"""知识库表：文档与切片（pgvector + tsvector）。

字段与索引见 docs/02-data-model.md §2.6。`embedding` 维度固定为 1024，
换 embedding 模型时先改配置与迁移，不允许运行期静默截断。

`tokens` 是应用层分词结果（中文单字 + 二元组），`tsv` 由它生成；这样
Postgres 默认分词器不认中文也能做倒排召回（见 app/rag/text.py）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default="indexed", server_default=text("'indexed'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    chunks: Mapped[list[KbChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False
    )
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    tokens: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    document: Mapped[KbDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_doc", "document_id", "ord"),
        Index("idx_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "idx_chunks_vec",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
