"""回答内容的按当前可见性回收（ADR-0022）：判定规则与多轮历史过滤。

端到端路径（详情 / 事件 / 重放）在 `test_runs_api.py` 与 `test_chat_stream.py`，
这里只钉纯判定逻辑，避免把「哪条规则」和「哪个接口」耦在一起。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.store import RunRecord, RunTurn
from app.rag.access import PUBLIC, ROLES, Viewer
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase
from app.runs.content import content_is_redacted, content_is_visible, filter_visible_turns


def _kb() -> KnowledgeBase:
    return KnowledgeBase(
        store=MemoryKnowledgeStore(),
        embedder=HashingEmbedder(),
        auto_seed=False,
    )


async def _index(
    kb: KnowledgeBase,
    *,
    visibility: str = PUBLIC,
    allowed_roles: tuple[str, ...] = (),
) -> str:
    info, _chunks = await kb.index_text(
        title="薪酬与年终奖",
        text="# 薪酬与年终奖\n\n## 年终奖\n\n年终奖在次年 1 月随工资发放。\n",
        source=f"seed:{uuid.uuid4().hex}.md",
        visibility=visibility,
        allowed_roles=allowed_roles,
    )
    return info.id


async def test_no_citations_is_always_visible() -> None:
    """工具类回答、拒答没有知识库引用，也就没有要回收的正文。"""
    kb = _kb()
    assert await content_is_visible(cited_document_ids=[], viewer=Viewer(), kb=kb) is True


async def test_admin_short_circuits() -> None:
    """知识库所有者（ADR-0019）不受文档级过滤约束，回收也一样。"""
    kb = _kb()
    doc_id = await _index(kb, visibility=ROLES, allowed_roles=("hr",))
    assert (
        await content_is_visible(
            cited_document_ids=[doc_id],
            viewer=Viewer(unrestricted=True),
            kb=kb,
        )
        is True
    )


async def test_any_invisible_document_hides_the_whole_answer() -> None:
    kb = _kb()
    public_id = await _index(kb)
    hr_id = await _index(kb, visibility=ROLES, allowed_roles=("hr",))
    employee = Viewer(roles=frozenset({"employee"}))

    assert await content_is_visible(cited_document_ids=[public_id], viewer=employee, kb=kb)
    assert (
        await content_is_visible(cited_document_ids=[public_id, hr_id], viewer=employee, kb=kb)
        is False
    )
    hr = Viewer(roles=frozenset({"hr"}))
    assert await content_is_visible(cited_document_ids=[public_id, hr_id], viewer=hr, kb=kb)


async def test_duplicate_ids_are_compared_as_a_set() -> None:
    kb = _kb()
    doc_id = await _index(kb)
    viewer = Viewer()
    assert await content_is_visible(cited_document_ids=[doc_id, doc_id], viewer=viewer, kb=kb)
    # 查不到的文档按不可见处理（fail-closed）
    assert (
        await content_is_visible(
            cited_document_ids=[doc_id, str(uuid.uuid4())], viewer=viewer, kb=kb
        )
        is False
    )


async def test_filter_visible_turns_drops_only_invisible_turns() -> None:
    kb = _kb()
    public_id = await _index(kb)
    hr_id = await _index(kb, visibility=ROLES, allowed_roles=("hr",))
    turns = [
        RunTurn(query="上一问", answer="上一答", cited_document_ids=(public_id,)),
        RunTurn(query="受限问", answer="受限答", cited_document_ids=(hr_id,)),
        RunTurn(query="工具问", answer="工具答"),
    ]

    employee = Viewer(roles=frozenset({"employee"}))
    assert await filter_visible_turns(turns, viewer=employee, kb=kb) == [turns[0], turns[2]]
    assert await filter_visible_turns(turns, viewer=Viewer(roles=frozenset({"hr"})), kb=kb) == turns
    assert await filter_visible_turns(turns, viewer=Viewer(unrestricted=True), kb=kb) == turns
    assert await filter_visible_turns([], viewer=employee, kb=kb) == []


async def test_pruned_content_is_never_redacted() -> None:
    """正文已按时间清空（ADR-0023）就不存在「按权限回收」：不能把过期说成越权。"""
    kb = _kb()
    hr_id = await _index(kb, visibility=ROLES, allowed_roles=("hr",))
    record = RunRecord(
        run_id=str(uuid.uuid4()),
        user_id="u_102",
        session_id="sess_1",
        input="",
        output=None,
        content_pruned_at=datetime.now(UTC),
        cited_document_ids=[hr_id],
    )
    employee = Viewer(roles=frozenset({"employee"}))

    assert await content_is_redacted(record, viewer=employee, kb=kb) is False
