"""Postgres 工具覆盖存储（W5 D22/D23，默认跳过）。

只验证存取契约；治理闸门本身在 `test_tools_guard.py` / `test_admin_tools.py`
用内存实现覆盖，不需要每个用例都连库。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.tools.policy import PostgresToolSettingStore, ToolOverride


@pytest_asyncio.fixture
async def pg_tool_settings() -> AsyncIterator[
    tuple[PostgresToolSettingStore, async_sessionmaker[AsyncSession]]
]:
    url = os.environ.get("ONCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 ONCALL_TEST_DATABASE_URL 指向一个可清空的测试库")

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield PostgresToolSettingStore(sessionmaker), sessionmaker
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_upsert_load_and_delete(
    pg_tool_settings: tuple[PostgresToolSettingStore, async_sessionmaker[AsyncSession]],
) -> None:
    store, _ = pg_tool_settings
    await store.upsert(
        "query_cmdb", ToolOverride(enabled=False, roles=("admin",)), updated_by="admin_1"
    )
    assert await store.load() == {"query_cmdb": ToolOverride(enabled=False, roles=("admin",))}

    await store.upsert("query_cmdb", ToolOverride(enabled=True, roles=()), updated_by="admin_1")
    assert (await store.load())["query_cmdb"] == ToolOverride(enabled=True, roles=())

    await store.upsert("query_cmdb", None, updated_by="admin_1")
    assert await store.load() == {}


async def test_replace_is_atomic_snapshot(
    pg_tool_settings: tuple[PostgresToolSettingStore, async_sessionmaker[AsyncSession]],
) -> None:
    store, _ = pg_tool_settings
    await store.upsert("query_cmdb", ToolOverride(enabled=False), updated_by="admin_1")
    await store.replace(
        {
            "query_cmdb": ToolOverride(enabled=True, roles=("admin",)),
            "create_ticket": ToolOverride(enabled=False),
        },
        updated_by="admin_1",
    )
    loaded = await store.load()
    assert loaded["query_cmdb"] == ToolOverride(enabled=True, roles=("admin",))
    assert loaded["create_ticket"] == ToolOverride(enabled=False)

    await store.replace({}, updated_by="admin_1")
    assert await store.load() == {}
