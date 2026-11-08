"""检索增强（W2 D6-D10）。

模块划分：
    parse.py     文档解析（PDF / DOCX / MD / TXT）
    chunk.py     结构切分（按标题层级，超长再递归）
    text.py      中文分词（单字 + 二元组）与 tsvector token 串
    embed.py     向量化（确定性哈希 / OpenAI 兼容 HTTP）
    retrieve.py  混合检索（tsvector + pgvector + RRF）+ 重排 + 阈值
    repository.py pgvector 持久化（业务代码不直接写向量 SQL）
    memory.py    内存实现（测试 / 无库 demo）
    service.py   单例装配

约束：
- `Retriever` 是协议，允许替换 pgvector -> Qdrant/Milvus（见 ADR-0004）
- 业务代码不得直接写向量 SQL
"""

from __future__ import annotations

from app.rag.retrieve import KnowledgeBase, Retriever
from app.rag.types import ChunkRow, DocumentInfo, Hit, KnowledgeStore, Ranked

__all__ = [
    "ChunkRow",
    "DocumentInfo",
    "Hit",
    "KnowledgeBase",
    "KnowledgeStore",
    "Ranked",
    "Retriever",
]
