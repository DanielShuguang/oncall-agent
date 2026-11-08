"""知识库单例装配。

- `rag_backend=auto`：store 用 Postgres 时走 pgvector，否则内存
- 内存模式首次访问自动载入 seed 语料（50 篇），无库也能演示 RAG
- Postgres 模式不自动灌数据：必须显式 `make seed`，避免生产被演示数据污染

测试通过 `reset_knowledge_base()` 拿到干净实例。
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.rag.embed import build_embedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase
from app.rag.types import KnowledgeStore

_kb: KnowledgeBase | None = None


def resolve_backend(settings: Settings) -> str:
    if settings.rag_backend != "auto":
        return settings.rag_backend
    return "postgres" if settings.store_backend == "postgres" else "memory"


def build_knowledge_base(settings: Settings | None = None) -> KnowledgeBase:
    resolved = settings or get_settings()
    backend = resolve_backend(resolved)
    store: KnowledgeStore
    auto_seed = False
    if backend == "memory":
        store = MemoryKnowledgeStore()
        auto_seed = True
    elif backend == "postgres":
        from app.rag.repository import PgKnowledgeStore

        store = PgKnowledgeStore(get_sessionmaker())
    else:
        raise ValueError(f"未知 ONCALL_RAG_BACKEND: {resolved.rag_backend!r}")

    return KnowledgeBase(
        store=store,
        embedder=build_embedder(resolved),
        top_k=resolved.rag_top_k,
        candidates=resolved.rag_candidates,
        min_score=resolved.rag_min_score,
        rrf_k=resolved.rag_rrf_k,
        auto_seed=auto_seed,
    )


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = build_knowledge_base()
    return _kb


def set_knowledge_base(value: KnowledgeBase | None) -> None:
    global _kb
    _kb = value


def reset_knowledge_base(*, seed: bool = True) -> KnowledgeBase:
    """测试钩子：重置单例；`seed=False` 时内存库为空。"""
    global _kb
    base = build_knowledge_base()
    if not seed:
        base.auto_seed = False
    _kb = base
    return base
