"""pgvector 集成测试：真实 HNSW + tsvector 检索（默认跳过）。

设置 `ONCALL_TEST_DATABASE_URL=postgresql+asyncpg://.../oncall_test` 后运行，
与 `test_store_contract.py` 共用同一个可清空的测试库。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
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
    sparse = await pg_kb.store.sparse_search(["vpn", "客户端"], 5)
    vector = (await pg_kb.embedder.embed(["VPN 连不上"]))[0]
    dense = await pg_kb.store.dense_search(vector, 5)
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
