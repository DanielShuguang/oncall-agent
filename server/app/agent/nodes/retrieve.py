"""retrieve 节点：规则检索（W2 D9）。

节点是纯函数 `(state, deps) -> dict`：
- 只通过 `deps.retriever` 访问知识库，不直接写 SQL
- 检索异常降级为空召回，由 finalize 走兜底话术；不能让一次检索失败把 run 打挂
- 不发事件（R5），步骤事件由 runtime 统一发

多轮（ADR-0020 / ADR-0025）：
- 追问默认把最近几轮问题拼进检索词（`context_query`）
- 但如果追问句自己就点名了一篇文档（「那报销怎么走」），原句优先：拼上文只会把
  《差旅报销流程》稀释成上一轮的保修文档
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agent.deps import AgentDeps
from app.agent.history import contextual_query, topic_head
from app.agent.state import AgentState
from app.core.logging import get_logger
from app.rag.text import tokenize
from app.rag.types import Hit

log = get_logger(__name__)

#: 原句自足的判定：第一名文档要比第二名至少高这么多分（同一篇文档的切片不参与比较）。
#: 0.10 是实测的「明显领先」线：没点名新话题的追问分差只有 0.006–0.056；切换用例里
#: 两条有第二名（那报销怎么走 0.213 / 那会议室怎么订 0.316），另两条只有一篇文档。
#: 「那差旅怎么申请」0.547 vs 0.530 是已知漏判，按现在的口径仍拼上文。口径见
#: docs/eval/multiturn-v2.md，回归由 `make eval-multiturn` 守着。
STANDALONE_MARGIN = 0.10


def names_top_document(query: str, hits: Sequence[Hit]) -> bool:
    """这句追问自己就点到了第一名文档吗？（ADR-0025）

    两个证据缺一不可：

    1. **话题头出现在标题里**：「那报销」的「报销」在《差旅报销流程》标题里；
       「那怎么处理」的话题头只剩一个「那」，「处理」只是问法里的谓语，不是话题
    2. **第一名明显领先**：泛化追问（「那怎么申请」）也能检索到文档，但《工位调整
       申请》《停车位申请说明》《软件安装流程》的分数咬在一起，说明原句并没有
       点到哪一篇——这时拼上文反而更可信

    只有两条都成立才丢掉上文，所以漏判的代价是「退化成现在的合并行为」，不会
    比现在更差。函数不依赖 `hits` 的顺序；候选里只有一篇文档时没有第二名可比，
    置信度只剩标题证据（候选只有 top-5，见 ADR-0025 的「待定」）。
    """
    head = topic_head(query)
    if not head or not hits:
        return False
    top = max(hits, key=lambda hit: hit.score)
    head_tokens = {token for token in tokenize(head) if len(token) >= 2}
    title_tokens = {token for token in tokenize(top.title) if len(token) >= 2}
    if not head_tokens & title_tokens:
        return False
    others = [hit.score for hit in hits if hit.document_id != top.document_id]
    runner_up = max(others) if others else None
    return runner_up is None or top.score - runner_up >= STANDALONE_MARGIN


async def retrieve_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    query = state.get("query", "").strip()
    # 追问（"那怎么办"）单独拿去检索几乎没有任何可匹配的词：把上一轮问题拼进来，
    # 但只在判定为追问时这么做，独立问题不受影响（ADR-0020）
    context_query = contextual_query(query, state.get("messages", []))
    if deps.retriever is None or not context_query:
        return _empty(context_query)

    if context_query != query:
        # 原句优先（ADR-0025）：先按原句检索一次，只有它自己点不出具体文档时才拼上文。
        # 原句检索失败按「点不出」处理、继续走合并查询：多一次检索不能让 run 更容易挂。
        try:
            standalone = await deps.retriever.search(query, top_k=deps.top_k, viewer=deps.viewer)
        except Exception:
            log.exception("retrieval_failed", run_id=state.get("run_id"), query=query[:80])
            standalone = []
        if names_top_document(query, standalone):
            top = max(standalone, key=lambda hit: hit.score)
            log.info(
                "retrieval_followup_standalone",
                run_id=state.get("run_id"),
                query=query[:80],
                context_query=context_query[:160],
                title=top.title,
            )
            return _result(standalone, context_query=query)

    try:
        hits = await deps.retriever.search(context_query, top_k=deps.top_k, viewer=deps.viewer)
    except Exception:
        log.exception("retrieval_failed", run_id=state.get("run_id"))
        return _empty(context_query)
    if context_query != query:
        # 追问判定是启发式：把实际检索用的查询打进日志，坏例才能按日志收敛（ADR-0020）
        log.info(
            "retrieval_context_merged",
            run_id=state.get("run_id"),
            query=query[:80],
            context_query=context_query[:160],
        )
    return _result(hits, context_query=context_query)


def _empty(context_query: str) -> dict[str, Any]:
    return {"retrieved": [], "citations": [], "context_query": context_query}


def _result(hits: Sequence[Hit], *, context_query: str) -> dict[str, Any]:
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
