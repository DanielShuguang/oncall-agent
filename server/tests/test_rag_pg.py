"""pgvector 集成测试：真实 HNSW + tsvector 检索（默认跳过）。

设置 `ONCALL_TEST_DATABASE_URL=postgresql+asyncpg://.../oncall_test` 后运行，
与 `test_store_contract.py` 共用同一个可清空的测试库。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.rag.access import PUBLIC, ROLES, Viewer, is_visible
from app.rag.embed import HashingEmbedder
from app.rag.repository import PgKnowledgeStore
from app.rag.retrieve import KnowledgeBase


@pytest_asyncio.fixture
async def pg_kb() -> AsyncIterator[KnowledgeBase]:
    url = os.environ.get("ONCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 ONCALL_TEST_DATABASE_URL 指向一个可清空的测试库")

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    knowledge = KnowledgeBase(
        store=PgKnowledgeStore(sessionmaker),
        embedder=HashingEmbedder(),
        auto_seed=False,
    )
    try:
        yield knowledge
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_pg_hybrid_search_and_threshold(pg_kb: KnowledgeBase) -> None:
    await pg_kb.index_text(
        title="VPN 连接失败排查指南",
        text=(
            "# VPN 连接失败排查指南\n\n## 客户端\n\n"
            "VPN 连不上时先从内网软件库下载新版客户端，旧版 PPTP 已停用。\n\n"
            "## 错误码\n\nERR-502 表示认证失败，先重置密码。\n"
        ),
        source="seed:vpn.md",
    )
    await pg_kb.index_text(
        title="打印机离线排查指南",
        text="# 打印机离线排查指南\n\n先确认打印机与电脑在同一网段，再重启 Print Spooler。",
        source="seed:printer.md",
    )
    await pg_kb.index_text(
        title="会议室预订规则",
        text="# 会议室预订规则\n\n在 OA 会议室模块预订，提前 15 分钟签到。",
        source="seed:meeting.md",
    )

    assert await pg_kb.chunk_count() >= 3

    # D8 验收：两条通道各自都能返回结果
    sparse = await pg_kb.store.sparse_search(["vpn", "客户端"], 5, viewer=Viewer())
    vector = (await pg_kb.embedder.embed(["VPN 连不上"]))[0]
    dense = await pg_kb.store.dense_search(vector, 5, viewer=Viewer())
    assert sparse and dense

    hits = await pg_kb.search("VPN 连不上怎么办")
    assert hits
    assert hits[0].title == "VPN 连接失败排查指南"
    assert all(hit.score >= 0.38 for hit in hits)

    assert await pg_kb.search("公司年会抽奖规则") == []

    about_printer = await pg_kb.search("打印机离线")
    assert about_printer[0].title == "打印机离线排查指南"
    assert "Print Spooler" in about_printer[0].content


async def test_pg_reindex_keeps_search_working(pg_kb: KnowledgeBase) -> None:
    await pg_kb.index_text(
        title="密码重置",
        text="# 密码重置\n\n在 SSO 门户点击忘记密码，通过手机号验证。",
        source="seed:password.md",
    )
    assert await pg_kb.reindex() >= 1
    hits = await pg_kb.search("忘记密码怎么重置")
    assert hits and hits[0].title == "密码重置"


async def test_pg_upload_replaces_same_source(pg_kb: KnowledgeBase) -> None:
    await pg_kb.index_text(
        title="旧标题",
        text="# 旧标题\n\n旧内容：重启 Print Spooler。",
        source="upload:guide.md",
    )
    await pg_kb.index_text(
        title="新标题",
        text="# 新标题\n\n新内容：删除设备后重新添加打印机。",
        source="upload:guide.md",
    )
    documents = await pg_kb.list_documents()
    assert len(documents) == 1
    assert documents[0].title == "新标题"
    assert await pg_kb.search("重启 Print Spooler") == []


async def test_pg_get_document_reads_display_columns_only(pg_kb: KnowledgeBase) -> None:
    """详情/引用全文是展示路径：不读 embedding/tsv/tokens（200 段会白读 ~1MB）。"""
    info, _chunks = await pg_kb.index_text(
        title="访客网络",
        text=(
            "# 访客网络\n\n## 登记\n\n访客由接待人提前一天登记。\n\n## 连接\n\n用手机号验证码登录。"
        ),
        source="seed:guest.md",
    )

    result = await pg_kb.get_document(info.id, viewer=Viewer())

    assert result is not None
    _, rows = result
    assert [row.ord for row in rows] == sorted(row.ord for row in rows)
    assert rows and "接待人" in rows[0].content
    assert all(row.content for row in rows)
    assert all(row.tokens == "" for row in rows)


#: (visibility, allowed_roles, viewer_roles, unrestricted)
_ACL_DOCS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (PUBLIC, ()),
    (ROLES, ("hr",)),
    (ROLES, ("hr", "finance")),
    (ROLES, ("approver",)),
)
_ACL_VIEWERS: tuple[tuple[frozenset[str], bool], ...] = (
    (frozenset(), False),
    (frozenset({"employee"}), False),
    (frozenset({"hr"}), False),
    (frozenset({"finance"}), False),
    (frozenset({"hr", "employee"}), False),
    (frozenset({"employee"}), True),
)


async def test_pg_visibility_filter_matches_rule_matrix(pg_kb: KnowledgeBase) -> None:
    """SQL 过滤与 `is_visible` 必须同一条规则：扫描每个 (文档 × 调用者) 组合。"""
    chunk_ids: list[set[int]] = []
    for index, (visibility, roles) in enumerate(_ACL_DOCS):
        info, _chunks = await pg_kb.index_text(
            title=f"ACL 探针 {index}",
            text=f"# ACL 探针 {index}\n\n## 内容\n\naclprobe{index} 权限测试句子。",
            source=f"acl:{index}",
            visibility=visibility,
            allowed_roles=roles,
        )
        result = await pg_kb.get_document(info.id, viewer=Viewer(unrestricted=True))
        assert result is not None
        chunk_ids.append({row.chunk_id for row in result[1]})

    total = await pg_kb.chunk_count()
    for index, (visibility, roles) in enumerate(_ACL_DOCS):
        vector = (await pg_kb.embedder.embed([f"aclprobe{index}"]))[0]
        for viewer_roles, unrestricted in _ACL_VIEWERS:
            viewer = Viewer(roles=viewer_roles, unrestricted=unrestricted)
            expected = is_visible(visibility=visibility, allowed_roles=roles, viewer=viewer)
            where = (visibility, roles, viewer_roles, unrestricted)

            sparse = await pg_kb.store.sparse_search([f"aclprobe{index}"], 10, viewer=viewer)
            assert bool(sparse) is expected, where
            assert {row.chunk_id for row in sparse} <= chunk_ids[index], where

            dense = await pg_kb.store.dense_search(vector, total, viewer=viewer)
            hit = chunk_ids[index] & {row.chunk_id for row in dense}
            assert bool(hit) is expected, where


async def test_pg_visible_document_ids_matches_rule(pg_kb: KnowledgeBase) -> None:
    """批量校验（ADR-0022）复用召回的同一条 SQL 条件，逐组合对 `is_visible`。"""
    ids: list[str] = []
    for index, (visibility, roles) in enumerate(_ACL_DOCS):
        info, _chunks = await pg_kb.index_text(
            title=f"ACL 批量探针 {index}",
            text=f"# ACL 批量探针 {index}\n\n## 内容\n\n可见性批量校验 {index}。",
            source=f"acl:batch:{index}",
            visibility=visibility,
            allowed_roles=roles,
        )
        ids.append(info.id)

    query = [*ids, str(uuid.uuid4()), "not-a-uuid"]
    for viewer_roles, unrestricted in _ACL_VIEWERS:
        viewer = Viewer(roles=viewer_roles, unrestricted=unrestricted)
        expected = {
            document_id
            for document_id, (visibility, roles) in zip(ids, _ACL_DOCS, strict=True)
            if is_visible(visibility=visibility, allowed_roles=roles, viewer=viewer)
        }
        assert await pg_kb.visible_document_ids(query, viewer=viewer) == expected
    assert await pg_kb.visible_document_ids([], viewer=Viewer()) == set()


async def test_pg_limit_applies_after_visibility_filter(pg_kb: KnowledgeBase) -> None:
    """受限文档不能占掉候选名额：limit=2 时必须拿到 2 条公开切片。"""
    for index in range(3):
        await pg_kb.index_text(
            title=f"受限文档 {index}",
            text=f"# 受限文档 {index}\n\n## 正文\n\nspooler 队列清理说明 {index}。",
            source=f"acl:limit-r{index}",
            visibility=ROLES,
            allowed_roles=("hr",),
        )
    for index in range(2):
        await pg_kb.index_text(
            title=f"公开文档 {index}",
            text=f"# 公开文档 {index}\n\n## 正文\n\nspooler 队列清理说明 {index}。",
            source=f"acl:limit-p{index}",
        )

    sparse = await pg_kb.store.sparse_search(["spooler"], 2, viewer=Viewer())
    assert len(sparse) == 2
    rows = await pg_kb.store.fetch_chunks([row.chunk_id for row in sparse])
    assert {row.title for row in rows.values()} == {"公开文档 0", "公开文档 1"}


async def test_pg_search_respects_access_and_set_access(pg_kb: KnowledgeBase) -> None:
    info, _chunks = await pg_kb.index_text(
        title="薪酬、年终奖与工资条查询（HR 专用）",
        text="# 薪酬\n\n## 年终奖\n\n年终奖在次年 1 月随工资发放，按绩效系数计算。",
        source="acl:hr",
        visibility=ROLES,
        allowed_roles=("hr",),
    )

    assert await pg_kb.search("年终奖什么时候发") == []
    as_hr = await pg_kb.search("年终奖什么时候发", viewer=Viewer(roles=frozenset({"hr"})))
    assert as_hr and as_hr[0].document_id == info.id
    owner = await pg_kb.search("年终奖什么时候发", viewer=Viewer(unrestricted=True))
    assert owner and owner[0].document_id == info.id

    updated = await pg_kb.set_access(info.id, visibility=PUBLIC, allowed_roles=())
    assert updated is not None and updated.visibility == PUBLIC
    assert await pg_kb.search("年终奖什么时候发")

    listed = await pg_kb.list_documents()
    assert [doc.visibility for doc in listed] == [PUBLIC]
    assert listed[0].allowed_roles == ()


async def test_pg_check_constraint_rejects_ambiguous_access(pg_kb: KnowledgeBase) -> None:
    """DB CHECK 兜住「public 带角色」：Python 校验被绕过时也不能写进脏数据。"""
    with pytest.raises(IntegrityError):
        await pg_kb.set_access(
            (await pg_kb.index_text(title="探针", text="# 探针\n\n正文。", source="acl:check"))[
                0
            ].id,
            visibility=PUBLIC,
            allowed_roles=("hr",),
        )
