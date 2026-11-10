"""pgvector 持久化。

故意把 SQL 都关在这里：业务代码只依赖 `KnowledgeStore` 协议（ADR-0004）。
稀疏通道用 `ts_rank_cd`（Postgres 全文排序，不是严格 BM25），稠密通道用
HNSW cosine；两路返回的排名在 `KnowledgeBase` 里做 RRF 融合。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kb import KbChunk as KbChunkRow
from app.models.kb import KbDocument as KbDocumentRow
from app.rag.access import PUBLIC, Viewer
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
        visibility: str = PUBLIC,
        allowed_roles: Sequence[str] = (),
    ) -> DocumentInfo:
        document_id = uuid.uuid4()
        now = datetime.now(UTC)
        roles = tuple(allowed_roles)
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
                    visibility=visibility,
                    allowed_roles=list(roles),
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
            visibility=visibility,
            allowed_roles=roles,
        )

    async def set_access(
        self, document_id: str, *, visibility: str, allowed_roles: Sequence[str]
    ) -> DocumentInfo | None:
        try:
            rid = uuid.UUID(document_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session, session.begin():
            document = await session.get(KbDocumentRow, rid)
            if document is None:
                return None
            document.visibility = visibility
            document.allowed_roles = list(allowed_roles)
            info = _info(document)
        return info

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
            # 只选展示列：详情与引用全文都不需要 embedding/tsv/tokens，
            # 而一段 1024 维向量约 4KB，200 段的文档会白读 ~1MB 以上
            rows = (
                await session.execute(
                    select(
                        KbChunkRow.id,
                        KbChunkRow.ord,
                        KbChunkRow.heading,
                        KbChunkRow.content,
                        KbChunkRow.page,
                    )
                    .where(KbChunkRow.document_id == rid)
                    .order_by(KbChunkRow.ord)
                )
            ).all()
            info = _info(document)
        return info, [
            ChunkRow(
                chunk_id=row.id,
                document_id=str(rid),
                ord=row.ord,
                title=info.title,
                source=info.source,
                heading=row.heading,
                content=row.content,
                page=row.page,
                tokens="",
            )
            for row in rows
        ]

    async def visible_document_ids(
        self, document_ids: Sequence[str], *, viewer: Viewer
    ) -> set[str]:
        """与召回侧同一条可见性条件（ADR-0019/0022）：`_visibility_clause`。

        非法 UUID 与不存在的文档都直接不在结果里——调用方按 fail-closed 处理。
        """
        ids: list[uuid.UUID] = []
        for raw in document_ids:
            try:
                ids.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        if not ids:
            return set()
        stmt = select(KbDocumentRow.id).where(KbDocumentRow.id.in_(ids))
        clause = _visibility_clause(viewer)
        if clause is not None:
            stmt = stmt.where(clause)
        async with self._sessionmaker() as session:
            return {str(rid) for rid in (await session.scalars(stmt)).all()}

    async def chunk_count(self) -> int:
        async with self._sessionmaker() as session:
            return int(await session.scalar(select(func.count()).select_from(KbChunkRow)) or 0)

    async def sparse_search(
        self, query_tokens: Sequence[str], limit: int, *, viewer: Viewer
    ) -> list[Ranked]:
        tokens = list(dict.fromkeys(query_tokens))[:64]
        if not tokens:
            return []
        # 每个 lexeme 用单引号包住，避免型号里的 - / . 被 tsquery 当成语法
        query = " | ".join(f"'{token}'" for token in tokens)
        tsquery = func.to_tsquery("simple", query)
        score = func.ts_rank_cd(KbChunkRow.tsv, tsquery)
        statement = (
            select(KbChunkRow.id, score.label("score"))
            .join(KbDocumentRow, KbDocumentRow.id == KbChunkRow.document_id)
            .where(KbChunkRow.tsv.op("@@")(tsquery))
        )
        clause = _visibility_clause(viewer)
        if clause is not None:
            statement = statement.where(clause)
        statement = statement.order_by(score.desc(), KbChunkRow.id).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.execute(statement)).all()
        return [Ranked(chunk_id=int(row.id), score=float(row.score)) for row in rows]

    async def dense_search(
        self, query_vector: Sequence[float], limit: int, *, viewer: Viewer
    ) -> list[Ranked]:
        distance = KbChunkRow.embedding.cosine_distance(list(query_vector))
        statement = select(KbChunkRow.id, (1 - distance).label("score")).join(
            KbDocumentRow, KbDocumentRow.id == KbChunkRow.document_id
        )
        clause = _visibility_clause(viewer)
        if clause is not None:
            statement = statement.where(clause)
        statement = statement.order_by(distance, KbChunkRow.id).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.execute(statement)).all()
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


def _visibility_clause(viewer: Viewer) -> ColumnElement[bool] | None:
    """召回侧可见性条件；`None` 表示不过滤（知识库所有者）。

    这条 SQL 与 `access.is_visible` 是同一条规则的两个实现，
    两者一致性由 `tests/test_rag_acl.py` 的矩阵用例守住（ADR-0019）。
    """
    if viewer.unrestricted:
        return None
    clauses: list[ColumnElement[bool]] = [KbDocumentRow.visibility == PUBLIC]
    if viewer.roles:
        clauses.append(KbDocumentRow.allowed_roles.overlap(sorted(viewer.roles)))
    return or_(*clauses)


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
        visibility=row.visibility,
        allowed_roles=tuple(row.allowed_roles or ()),
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
