"""混合检索与引用：排序、阈值、归档文档不进入回答。"""

from __future__ import annotations

from app.agent.deps import AgentDeps
from app.agent.nodes.finalize import compose_answer
from app.agent.nodes.retrieve import retrieve_node
from app.agent.state import initial_state
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
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


async def test_numbered_list_is_not_numbered_twice() -> None:
    """正文里的 "1. " 编号要去掉，回答模板自己会加序号。"""
    kb = KnowledgeBase(MemoryKnowledgeStore(), HashingEmbedder(), auto_seed=False)
    await kb.index_text(
        title="远程办公接入说明",
        text=(
            "# 远程办公接入说明\n\n## 客户端安装\n\n"
            "1. 打开设置页面，进入网络中心。\n"
            "2. 下载并安装远程办公客户端。\n"
            "3. 用企业邮箱登录后重试。\n"
        ),
        source="upload:remote.md",
    )
    deps = AgentDeps(guard=ToolGuard(build_registry()), retriever=kb)
    state = initial_state(run_id="run", user={"id": "u_102"}, query="远程办公客户端怎么安装")
    state = {**state, **await retrieve_node(state, deps)}

    answer, citations = compose_answer(state)
    assert citations
    assert "1. 1." not in answer
    assert "1. 2." not in answer


async def test_citation_filler_requires_score_floor() -> None:
    """补满 3 条引用不能拉低分噪声；同文档后续步骤可放宽到 0.6。"""
    state = initial_state(run_id="run", user={"id": "u_102"}, query="打印机显示离线怎么办")
    state["retrieved"] = [
        {
            "chunk_id": 1,
            "document_id": "d1",
            "ord": 0,
            "title": "打印机离线排查指南",
            "heading": "打印机离线排查指南 > 先确认打印机状态",
            "content": "打印机显示离线时，先确认电源与网线是否插好。",
            "score": 0.9,
        },
        {
            "chunk_id": 2,
            "document_id": "d1",
            "ord": 1,
            "title": "打印机离线排查指南",
            "heading": "打印机离线排查指南 > Windows 打印服务",
            "content": "在服务里找到 Print Spooler，先停止，再启动。",
            "score": 0.6,
        },
        {
            "chunk_id": 3,
            "document_id": "d2",
            "ord": 0,
            "title": "办公电话使用指南",
            "heading": "办公电话使用指南 > 注意事项",
            "content": "如有疑问请联系行政部门。",
            "score": 0.5,
        },
    ]
    state["citations"] = [
        {
            "chunk_id": hit["chunk_id"],
            "title": hit["title"],
            "heading": hit["heading"],
            "snippet": hit["content"],
        }
        for hit in state["retrieved"]
    ]

    answer, citations = compose_answer(state)
    assert "Print Spooler" in answer
    assert [citation["title"] for citation in citations] == ["打印机离线排查指南"] * 2


async def test_archived_top_hit_does_not_suppress_valid_citations() -> None:
    """归档文档拿到最高分时，不能用它计算阈值把在用文档压掉。"""
    state = initial_state(run_id="run", user={"id": "u_102"}, query="VPN 客户端在哪里下载")
    state["retrieved"] = [
        {
            "chunk_id": 1,
            "document_id": "old",
            "ord": 0,
            "title": "【已归档】VPN 旧版客户端使用说明（PPTP）",
            "heading": "【已归档】VPN 旧版客户端使用说明（PPTP） > 安装",
            "content": "从旧版共享目录安装 PPTP 客户端。",
            "score": 0.99,
        },
        {
            "chunk_id": 2,
            "document_id": "new",
            "ord": 0,
            "title": "VPN 连接失败排查指南",
            "heading": "VPN 连接失败排查指南 > 客户端下载与安装",
            "content": "请从内网软件库下载 Windows 版 VPN 客户端，版本号不低于 5.2。",
            "score": 0.7,
        },
    ]
    state["citations"] = [
        {
            "chunk_id": hit["chunk_id"],
            "title": hit["title"],
            "heading": hit["heading"],
            "snippet": hit["content"],
        }
        for hit in state["retrieved"]
    ]

    answer, citations = compose_answer(state)
    assert "内网软件库" in answer
    assert [citation["title"] for citation in citations] == ["VPN 连接失败排查指南"]
