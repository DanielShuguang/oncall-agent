"""内存知识库：测试、无库 demo 与 seed 语料共用同一套检索接口。

它和 pgvector 实现返回同一种 `Ranked` / `ChunkRow`，所以
`KnowledgeBase` 的融合、重排、阈值逻辑两边完全一致。
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.rag.embed import cosine
from app.rag.types import ChunkRow, DocumentInfo, Ranked, StoredChunk


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self._docs: dict[str, DocumentInfo] = {}
        self._chunks: dict[int, ChunkRow] = {}
        self._vectors: dict[int, list[float]] = {}
        self._by_source: dict[str, str] = {}
        self._next_chunk_id = 1

    async def add_document(
        self,
        *,
        title: str,
        source: str,
        checksum: str,
        chunks: Sequence[StoredChunk],
        version: str | None = None,
    ) -> DocumentInfo:
        document_id = str(uuid.uuid4())
        info = DocumentInfo(
            id=document_id,
            title=title,
            source=source,
            checksum=checksum,
            chunk_count=len(chunks),
            status="indexed",
            created_at=datetime.now(UTC),
            version=version,
        )
        self._docs[document_id] = info
        self._by_source[source] = document_id
        for chunk in chunks:
            chunk_id = self._next_chunk_id
            self._next_chunk_id += 1
            self._chunks[chunk_id] = ChunkRow(
                chunk_id=chunk_id,
                document_id=document_id,
                ord=chunk.ord,
                title=title,
                source=source,
                heading=chunk.heading,
                content=chunk.text,
                page=chunk.page,
                tokens=chunk.tokens,
            )
            self._vectors[chunk_id] = list(chunk.embedding)
        return info

    async def delete_by_source(self, source: str) -> None:
        document_id = self._by_source.pop(source, None)
        if document_id is None:
            return
        self._docs.pop(document_id, None)
        for chunk_id in [
            cid for cid, row in self._chunks.items() if row.document_id == document_id
        ]:
            self._chunks.pop(chunk_id, None)
            self._vectors.pop(chunk_id, None)

    async def list_documents(self) -> list[DocumentInfo]:
        return sorted(self._docs.values(), key=lambda doc: doc.created_at, reverse=True)

    async def get_document(self, document_id: str) -> tuple[DocumentInfo, list[ChunkRow]] | None:
        info = self._docs.get(document_id)
        if info is None:
            return None
        rows = sorted(
            (row for row in self._chunks.values() if row.document_id == document_id),
            key=lambda row: row.ord,
        )
        return info, rows

    async def chunk_count(self) -> int:
        return len(self._chunks)

    async def sparse_search(self, query_tokens: Sequence[str], limit: int) -> list[Ranked]:
        query = set(query_tokens)
        if not query:
            return []
        scored: list[Ranked] = []
        for chunk_id, row in self._chunks.items():
            chunk_tokens = set(row.tokens.split())
            overlap = len(query & chunk_tokens)
            if overlap == 0:
                continue
            score = overlap / math.sqrt(len(query) * max(1, len(chunk_tokens)))
            scored.append(Ranked(chunk_id=chunk_id, score=score))
        scored.sort(key=lambda item: (-item.score, item.chunk_id))
        return scored[:limit]

    async def dense_search(self, query_vector: Sequence[float], limit: int) -> list[Ranked]:
        scored = [
            Ranked(chunk_id=chunk_id, score=cosine(query_vector, vector))
            for chunk_id, vector in self._vectors.items()
        ]
        scored.sort(key=lambda item: (-item.score, item.chunk_id))
        return scored[:limit]

    async def fetch_chunks(self, chunk_ids: Sequence[int]) -> Mapping[int, ChunkRow]:
        return {cid: self._chunks[cid] for cid in chunk_ids if cid in self._chunks}

    async def all_chunks(self) -> list[ChunkRow]:
        return sorted(self._chunks.values(), key=lambda row: row.chunk_id)

    async def replace_vectors(self, items: Sequence[tuple[int, str, list[float]]]) -> None:
        for chunk_id, tokens, vector in items:
            row = self._chunks.get(chunk_id)
            if row is None:
                continue
            self._chunks[chunk_id] = ChunkRow(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                ord=row.ord,
                title=row.title,
                source=row.source,
                heading=row.heading,
                content=row.content,
                page=row.page,
                tokens=tokens,
            )
            self._vectors[chunk_id] = list(vector)
