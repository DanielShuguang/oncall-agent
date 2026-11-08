"""pgvector 持久化。

故意把 SQL 都关在这里：业务代码只依赖 `KnowledgeStore` 协议（ADR-0004）。
稀疏通道用 `ts_rank_cd`（Postgres 全文排序，不是严格 BM25），稠密通道用
HNSW cosine；两路返回的排名在 `KnowledgeBase` 里做 RRF 融合。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kb import KbChunk as KbChunkRow
from app.models.kb import KbDocument as KbDocumentRow
from app.rag.types import ChunkRow, DocumentInfo, Ranked, StoredChunk


class PgKnowledgeStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def add_document(
        self,
        *,
        title: str,
        source: str,
        checksum: str,
        chunks: Sequence[StoredChunk],
        version: str | None = None,
    ) -> DocumentInfo:
        document_id = uuid.uuid4()
        now = datetime.now(UTC)
        async with self._sessionmaker() as session, session.begin():
            session.add(
                KbDocumentRow(
                    id=document_id,
                    title=title,
                    source=source,
                    version=version,
                    checksum=checksum,
                    chunk_count=len(chunks),
                    status="indexed",
                    created_at=now,
                )
            )
            for chunk in chunks:
                session.add(
                    KbChunkRow(
                        document_id=document_id,
                        ord=chunk.ord,
                        heading=chunk.heading,
                        content=chunk.text,
                        page=chunk.page,
                        tokens=chunk.tokens,
                        tsv=func.to_tsvector("simple", chunk.tokens),
                        embedding=chunk.embedding,
                    )
                )
        return DocumentInfo(
            id=str(document_id),
            title=title,
            source=source,
            checksum=checksum,
            chunk_count=len(chunks),
            status="indexed",
            created_at=now,
            version=version,
        )

    async def delete_by_source(self, source: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(delete(KbDocumentRow).where(KbDocumentRow.source == source))

    async def list_documents(self) -> list[DocumentInfo]:
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(KbDocumentRow).order_by(KbDocumentRow.created_at.desc())
                )
            ).all()
        return [_info(row) for row in rows]

    async def get_document(self, document_id: str) -> tuple[DocumentInfo, list[ChunkRow]] | None:
        try:
            rid = uuid.UUID(document_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            document = await session.get(KbDocumentRow, rid)
            if document is None:
                return None
            rows = (
                await session.scalars(
                    select(KbChunkRow).where(KbChunkRow.document_id == rid).order_by(KbChunkRow.ord)
                )
            ).all()
            info = _info(document)
        return info, [_chunk(row, info) for row in rows]

    async def chunk_count(self) -> int:
        async with self._sessionmaker() as session:
            return int(await session.scalar(select(func.count()).select_from(KbChunkRow)) or 0)

    async def sparse_search(self, query_tokens: Sequence[str], limit: int) -> list[Ranked]:
        tokens = list(dict.fromkeys(query_tokens))[:64]
        if not tokens:
            return []
        # 每个 lexeme 用单引号包住，避免型号里的 - / . 被 tsquery 当成语法
        query = " | ".join(f"'{token}'" for token in tokens)
        statement = text(
            """
            SELECT id, ts_rank_cd(tsv, to_tsquery('simple', :query)) AS score
            FROM kb_chunks
            WHERE tsv @@ to_tsquery('simple', :query)
            ORDER BY score DESC, id
            LIMIT :limit
            """
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(statement, {"query": query, "limit": limit})).all()
        return [Ranked(chunk_id=int(row.id), score=float(row.score)) for row in rows]

    async def dense_search(self, query_vector: Sequence[float], limit: int) -> list[Ranked]:
        statement = text(
            """
            SELECT id, 1 - (embedding <=> CAST(:vector AS vector)) AS score
            FROM kb_chunks
            ORDER BY embedding <=> CAST(:vector AS vector)
            LIMIT :limit
            """
        )
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    statement,
                    {"vector": _vector_literal(query_vector), "limit": limit},
                )
            ).all()
        return [Ranked(chunk_id=int(row.id), score=float(row.score)) for row in rows]

    async def fetch_chunks(self, chunk_ids: Sequence[int]) -> Mapping[int, ChunkRow]:
        if not chunk_ids:
            return {}
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(KbChunkRow, KbDocumentRow)
                    .join(KbDocumentRow, KbDocumentRow.id == KbChunkRow.document_id)
                    .where(KbChunkRow.id.in_(list(chunk_ids)))
                )
            ).all()
        result: dict[int, ChunkRow] = {}
        for chunk, document in rows:
            result[chunk.id] = _chunk(chunk, _info(document))
        return result

    async def all_chunks(self) -> list[ChunkRow]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(KbChunkRow, KbDocumentRow)
                    .join(KbDocumentRow, KbDocumentRow.id == KbChunkRow.document_id)
                    .order_by(KbChunkRow.id)
                )
            ).all()
        return [_chunk(chunk, _info(document)) for chunk, document in rows]

    async def replace_vectors(self, items: Sequence[tuple[int, str, list[float]]]) -> None:
        async with self._sessionmaker() as session, session.begin():
            for chunk_id, tokens, vector in items:
                await session.execute(
                    update(KbChunkRow)
                    .where(KbChunkRow.id == chunk_id)
                    .values(
                        tokens=tokens,
                        tsv=func.to_tsvector("simple", tokens),
                        embedding=vector,
                    )
                )


def _info(row: KbDocumentRow) -> DocumentInfo:
    return DocumentInfo(
        id=str(row.id),
        title=row.title,
        source=row.source,
        checksum=row.checksum,
        chunk_count=row.chunk_count,
        status=row.status,
        created_at=row.created_at,
        version=row.version,
    )


def _chunk(row: KbChunkRow, document: DocumentInfo) -> ChunkRow:
    return ChunkRow(
        chunk_id=row.id,
        document_id=str(row.document_id),
        ord=row.ord,
        title=document.title,
        source=document.source,
        heading=row.heading,
        content=row.content,
        page=row.page,
        tokens=row.tokens,
    )


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
