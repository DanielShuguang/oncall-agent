"""文档级可见性（ADR-0019）：规则矩阵、召回前过滤、预览同规则。

这些用例**不**碰数据库：SQL 侧的一致性由 `test_rag_pg.py` 用同一张矩阵复验。
"""

from __future__ import annotations

import pytest

from app.rag.access import (
    MAX_ROLES,
    PUBLIC,
    ROLES,
    Viewer,
    is_visible,
    parse_access,
    viewer_for,
)
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase


def _kb(*, seed: bool = False) -> KnowledgeBase:
    return KnowledgeBase(
        store=MemoryKnowledgeStore(),
        embedder=HashingEmbedder(),
        auto_seed=seed,
    )


async def _index(
    kb: KnowledgeBase,
    *,
    title: str,
    text: str,
    source: str,
    visibility: str = PUBLIC,
    allowed_roles: tuple[str, ...] = (),
) -> str:
    info, _chunks = await kb.index_text(
        title=title,
        text=text,
        source=source,
        visibility=visibility,
        allowed_roles=allowed_roles,
    )
    return info.id


HR_DOC = """# 薪酬、年终奖与工资条查询（HR 专用）

## 年终奖

年终奖在次年 1 月随工资发放，金额按绩效系数计算。
"""

PUBLIC_DOC = """# VPN 连接失败排查指南

## 客户端

VPN 连不上时先从内网软件库下载新版客户端。
"""


def test_visibility_rule_matrix() -> None:
    cases = [
        # (visibility, allowed_roles, viewer, expected)
        (PUBLIC, (), Viewer(), True),
        (PUBLIC, (), Viewer(roles=frozenset({"hr"})), True),
        (ROLES, ("hr",), Viewer(), False),
        (ROLES, ("hr",), Viewer(roles=frozenset({"employee"})), False),
        (ROLES, ("hr",), Viewer(roles=frozenset({"hr"})), True),
        (ROLES, ("hr", "finance"), Viewer(roles=frozenset({"finance"})), True),
        (ROLES, ("hr",), Viewer(roles=frozenset({"hr"}), unrestricted=True), True),
        (ROLES, ("hr",), Viewer(unrestricted=True), True),
    ]
    for visibility, roles, viewer, expected in cases:
        assert is_visible(visibility=visibility, allowed_roles=roles, viewer=viewer) is expected, (
            visibility,
            roles,
            viewer,
        )


def test_viewer_for_marks_knowledge_owner() -> None:
    assert viewer_for(["employee"], ["admin"]) == Viewer(roles=frozenset({"employee"}))
    owner = viewer_for(["employee", "admin"], ["admin", "kb_owner"])
    assert owner.unrestricted is True
    assert owner.roles == frozenset({"employee", "admin"})
    assert viewer_for(["kb_owner"], ["admin", "kb_owner"]).unrestricted is True


@pytest.mark.parametrize(
    ("visibility", "roles", "expected"),
    [
        ("public", "", (PUBLIC, ())),
        ("PUBLIC", "  ", (PUBLIC, ())),
        ("roles", "hr, finance ,hr", (ROLES, ("hr", "finance"))),
        ("roles", ["hr", "hr", " "], (ROLES, ("hr",))),
    ],
)
def test_parse_access_accepts_and_normalizes(
    visibility: str, roles: str | list[str], expected: tuple[str, tuple[str, ...]]
) -> None:
    assert parse_access(visibility, roles) == expected


@pytest.mark.parametrize(
    ("visibility", "roles"),
    [
        ("visible", ""),  # 未知可见性
        ("public", "hr"),  # 公开文档不能带角色（与 DB CHECK 一致）
        ("roles", ""),  # 指定角色必须至少一个
        ("roles", "hr admin"),  # 空格不是合法角色名
        ("roles", "人事"),  # 中文角色名会让签名侧对不上，直接拒绝
        ("roles", "x" * 33),  # 超长
        ("roles", [f"r{index}" for index in range(MAX_ROLES + 1)]),
    ],
)
def test_parse_access_rejects_ambiguous_input(visibility: str, roles: str | list[str]) -> None:
    with pytest.raises(ValueError):
        parse_access(visibility, roles)


async def test_search_hides_restricted_document_from_employee() -> None:
    kb = _kb()
    await _index(
        kb,
        title="薪酬、年终奖与工资条",
        text=HR_DOC,
        source="hr.md",
        visibility=ROLES,
        allowed_roles=("hr",),
    )
    await _index(kb, title="VPN 连接失败排查指南", text=PUBLIC_DOC, source="vpn.md")

    employee = await kb.search("年终奖什么时候发放")
    hr = await kb.search("年终奖什么时候发放", viewer=Viewer(roles=frozenset({"hr"})))
    owner = await kb.search("年终奖什么时候发放", viewer=Viewer(unrestricted=True))

    assert all("年终奖" not in hit.title for hit in employee)
    assert [hit.title for hit in hr] and "薪酬" in hr[0].title
    assert [hit.title for hit in owner] and "薪酬" in owner[0].title


async def test_restricted_chunks_never_reach_the_citation_payload() -> None:
    """引用是最容易泄露正文的出口：不可见文档不能出现在 citations 里。"""
    kb = _kb()
    hr_id = await _index(
        kb,
        title="薪酬、年终奖与工资条",
        text=HR_DOC,
        source="hr.md",
        visibility=ROLES,
        allowed_roles=("hr",),
    )
    hits = await kb.search("绩效系数 年终奖", viewer=Viewer(roles=frozenset({"employee"})))
    assert all(hit.document_id != hr_id for hit in hits)
    assert all("绩效系数" not in hit.citation()["snippet"] for hit in hits)


async def test_employee_candidates_are_filled_with_visible_documents() -> None:
    """过滤发生在取候选之前：不可见文档不能占掉名额把公开文档挤出去。"""
    kb = _kb()
    for index in range(3):
        await _index(
            kb,
            title=f"HR 政策 {index}",
            text=f"# HR 政策 {index}\n\n## 薪酬\n\n年终奖与绩效系数说明 {index}。\n",
            source=f"hr-{index}.md",
            visibility=ROLES,
            allowed_roles=("hr",),
        )
    for index in range(2):
        await _index(
            kb,
            title=f"入职指南 {index}",
            text=f"# 入职指南 {index}\n\n## 账号\n\n入职当天开通账号，绩效系数以 HR 通知为准。\n",
            source=f"onboarding-{index}.md",
        )

    employee = await kb.search("绩效系数", top_k=5)
    assert len(employee) == 2
    assert {hit.title for hit in employee} == {"入职指南 0", "入职指南 1"}


async def test_get_document_applies_the_same_rule() -> None:
    kb = _kb()
    document_id = await _index(
        kb,
        title="薪酬、年终奖与工资条",
        text=HR_DOC,
        source="hr.md",
        visibility=ROLES,
        allowed_roles=("hr",),
    )

    assert await kb.get_document(document_id, viewer=Viewer()) is None
    assert await kb.get_document(document_id, viewer=Viewer(roles=frozenset({"hr"}))) is not None
    assert await kb.get_document(document_id, viewer=Viewer(unrestricted=True)) is not None
    assert await kb.get_document("not-a-uuid", viewer=Viewer(unrestricted=True)) is None


async def test_set_access_switches_visibility_without_reindexing() -> None:
    kb = _kb()
    document_id = await _index(kb, title="薪酬、年终奖与工资条", text=HR_DOC, source="hr.md")

    assert await kb.search("年终奖什么时候发放")
    updated = await kb.set_access(document_id, visibility=ROLES, allowed_roles=("hr",))
    assert updated is not None and updated.visibility == ROLES
    assert await kb.search("年终奖什么时候发放") == []
    assert await kb.search("年终奖什么时候发放", viewer=Viewer(roles=frozenset({"hr"})))

    # chunk_id 不变：已有引用改可见范围后仍然能定位
    _info, rows = await kb.get_document(document_id, viewer=Viewer(unrestricted=True))
    assert rows and rows[0].chunk_id > 0
    assert await kb.set_access("missing", visibility=PUBLIC, allowed_roles=()) is None


async def test_seed_restricted_document_is_invisible_to_employees() -> None:
    """演示语料里的 HR 文档只给 `hr`：员工问年终奖仍然拒答（评测 neg-bonus 的金丝雀）。"""
    kb = _kb(seed=True)
    employee = await kb.search("公司年终奖什么时候发")
    assert all("HR 专用" not in hit.title for hit in employee)

    hr = await kb.search("公司年终奖什么时候发", viewer=Viewer(roles=frozenset({"hr"})))
    assert any("HR 专用" in hit.title for hit in hr)
