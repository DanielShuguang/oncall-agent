"""retrieve 节点：规则检索（W2 D9）。

节点是纯函数 `(state, deps) -> dict`：
- 只通过 `deps.retriever` 访问知识库，不直接写 SQL
- 检索异常降级为空召回，由 finalize 走兜底话术；不能让一次检索失败把 run 打挂
- 不发事件（R5），步骤事件由 runtime 统一发
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.history import contextual_query
from app.agent.state import AgentState
from app.core.logging import get_logger
from app.rag.types import Hit

log = get_logger(__name__)


async def retrieve_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    query = state.get("query", "").strip()
    # 追问（"那怎么办"）单独拿去检索几乎没有任何可匹配的词：把上一轮问题拼进来，
    # 但只在判定为追问时这么做，独立问题不受影响（ADR-0020）
    context_query = contextual_query(query, state.get("messages", []))
    if context_query != query:
        # 追问判定是启发式：把实际检索用的查询打进日志，坏例才能按日志收敛（ADR-0020）
        log.info(
            "retrieval_context_merged",
            run_id=state.get("run_id"),
            query=query[:80],
            context_query=context_query[:160],
        )
    if not context_query or deps.retriever is None:
        return {"retrieved": [], "citations": [], "context_query": context_query}
    try:
        hits = await deps.retriever.search(context_query, top_k=deps.top_k, viewer=deps.viewer)
    except Exception:
        log.exception("retrieval_failed", run_id=state.get("run_id"))
        return {"retrieved": [], "citations": [], "context_query": context_query}
    return {
        "retrieved": [_retrieved(hit) for hit in hits],
        "citations": [hit.citation() for hit in hits],
        "context_query": context_query,
    }


def _retrieved(hit: Hit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "ord": hit.ord,
        "title": hit.title,
        "heading": hit.heading,
        "content": hit.content,
        "page": hit.page,
        "score": hit.score,
    }
