"""RAG 的传输对象与存储协议。

拆成 types / store / retrieve 三层，是为了让「换向量库只换 store」成立：

    retrieve.py  融合、重排、阈值、引用（业务无关的检索策略）
    store.py     持久化（pgvector 或内存），不允许业务代码直接写向量 SQL
    index.py     解析 -> 切分 -> 向量化 -> 入库

`pgvector -> Qdrant/Milvus` 的替换点只在 `KnowledgeStore`（ADR-0004）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    id: str
    title: str
    source: str
    checksum: str
    chunk_count: int
    status: str
    created_at: datetime
    version: str | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class StoredChunk:
    """待入库的切片；tokens / embedding 由 indexer 算好。"""

    ord: int
    text: str
    heading: str | None
    page: int | None
    tokens: str
    embedding: list[float]
    is_table: bool = False


@dataclass(frozen=True, slots=True)
class ChunkRow:
    chunk_id: int
    document_id: str
    ord: int
    title: str
    source: str
    heading: str | None
    content: str
    page: int | None
    tokens: str


@dataclass(frozen=True, slots=True)
class Ranked:
    chunk_id: int
    score: float


@dataclass(frozen=True, slots=True)
class Hit:
    chunk_id: int
    document_id: str
    ord: int
    title: str
    heading: str | None
    content: str
    score: float
    page: int | None = None

    def citation(self, *, snippet_chars: int = 160) -> dict[str, Any]:
        snippet = self.content.strip().replace("\n", " ")
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars].rstrip() + "…"
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "ord": self.ord,
            "title": self.title,
            "heading": self.heading,
            "snippet": snippet,
            "page": self.page,
        }


class KnowledgeStore(Protocol):
    """向量库抽象。所有方法 async，换远程库时实现同一组方法即可。"""

    async def add_document(
        self,
        *,
        title: str,
        source: str,
        checksum: str,
        chunks: Sequence[StoredChunk],
        version: str | None = None,
        page_count: int | None = None,
    ) -> DocumentInfo: ...

    async def delete_by_source(self, source: str) -> None: ...

    async def list_documents(self) -> list[DocumentInfo]: ...

    async def get_document(
        self, document_id: str
    ) -> tuple[DocumentInfo, list[ChunkRow]] | None: ...

    async def chunk_count(self) -> int: ...

    async def sparse_search(self, query_tokens: Sequence[str], limit: int) -> list[Ranked]: ...

    async def dense_search(self, query_vector: Sequence[float], limit: int) -> list[Ranked]: ...

    async def fetch_chunks(self, chunk_ids: Sequence[int]) -> Mapping[int, ChunkRow]: ...

    async def all_chunks(self) -> list[ChunkRow]: ...

    async def replace_vectors(self, items: Sequence[tuple[int, str, list[float]]]) -> None: ...
