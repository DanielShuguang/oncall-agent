"""检索增强（W2 D7-D9 起实现）。

模块划分：
    parse.py     文档解析（PDF / DOCX / MD）
    chunk.py     结构切分（按标题层级，超长再递归）
    index.py     embedding 入库 + tsvector 建索引
    retrieve.py  混合检索（BM25 + 向量 + RRF）+ rerank
    cite.py      引用溯源（chunk_id -> 原文定位）

约束：
- `Retriever` 是协议，允许替换 pgvector -> Qdrant/Milvus（见 ADR-0004）
- 业务代码不得直接写向量 SQL
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class Hit:
    chunk_id: int
    document_id: str
    ord: int
    title: str
    heading: str | None
    content: str
    score: float


class Retriever(Protocol):
    async def search(self, query: str, top_k: int = 5) -> list[Hit]: ...
