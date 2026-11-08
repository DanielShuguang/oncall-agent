"""混合检索与引用：排序、阈值、归档文档不进入回答。"""

from __future__ import annotations

from app.agent.deps import AgentDeps
from app.agent.nodes.finalize import compose_answer
from app.agent.nodes.retrieve import retrieve_node
from app.agent.state import initial_state
from app.rag.retrieve import KnowledgeBase
from app.tools.builtin import build_registry
from app.tools.registry import ToolGuard


async def test_vpn_query_returns_vpn_chunks(memory_kb: KnowledgeBase) -> None:
    hits = await memory_kb.search("VPN 连不上怎么办")
    assert len(hits) >= 3
    assert [hit.title for hit in hits[:3]] == ["VPN 连接失败排查指南"] * 3
    assert all(hit.score >= 0.38 for hit in hits)
    assert hits[0].heading and hits[0].heading.startswith("VPN 连接失败排查指南")


async def test_out_of_kb_question_is_refused_by_threshold(memory_kb: KnowledgeBase) -> None:
    assert await memory_kb.search("公司年会抽奖规则是什么") == []
    assert await memory_kb.search("附近哪家咖啡店好喝") == []


async def test_archived_docs_never_enter_answer(memory_kb: KnowledgeBase) -> None:
    deps = AgentDeps(guard=ToolGuard(build_registry()), retriever=memory_kb)
    state = initial_state(run_id="run", user={"id": "u_102"}, query="VPN 客户端在哪里下载")
    state = {**state, **await retrieve_node(state, deps)}
    assert any("归档" in hit["title"] for hit in state["retrieved"])

    answer, citations = compose_answer(state)
    assert citations
    assert all("归档" not in citation["title"] for citation in citations)
    assert "已归档" not in answer


async def test_citation_contains_locator_fields(memory_kb: KnowledgeBase) -> None:
    hits = await memory_kb.search("打印机显示离线怎么办")
    citation = hits[0].citation()
    assert citation["chunk_id"] > 0
    assert citation["document_id"]
    assert citation["ord"] >= 0
    assert citation["snippet"]
    assert citation["title"] == "打印机离线排查指南"
