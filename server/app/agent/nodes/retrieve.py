"""retrieve 节点：规则检索（W2 D9）。

节点是纯函数 `(state, deps) -> dict`：
- 只通过 `deps.retriever` 访问知识库，不直接写 SQL
- 检索异常降级为空召回，由 finalize 走兜底话术；不能让一次检索失败把 run 打挂
- 不发事件（R5），步骤事件由 runtime 统一发
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import AgentState
from app.core.logging import get_logger
from app.rag.types import Hit

log = get_logger(__name__)


async def retrieve_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    query = state.get("query", "").strip()
    if not query or deps.retriever is None:
        return {"retrieved": [], "citations": []}
    try:
        hits = await deps.retriever.search(query, top_k=deps.top_k, viewer=deps.viewer)
    except Exception:
        log.exception("retrieval_failed", run_id=state.get("run_id"))
        return {"retrieved": [], "citations": []}
    return {
        "retrieved": [_retrieved(hit) for hit in hits],
        "citations": [hit.citation() for hit in hits],
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
