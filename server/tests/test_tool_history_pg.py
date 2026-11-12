"""Postgres 工具配置变更历史（ADR-0037，默认跳过）。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.tools.policy import (
    PostgresToolSettingStore,
    ToolOverride,
    ToolSettingChange,
)


@pytest_asyncio.fixture
async def pg_tool_history() -> AsyncIterator[PostgresToolSettingStore]:
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
        yield PostgresToolSettingStore(sessionmaker)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_upsert_and_replace_persist_history(
    pg_tool_history: PostgresToolSettingStore,
) -> None:
    store = pg_tool_history
    await store.upsert(
        "query_cmdb",
        ToolOverride(enabled=False),
        updated_by="admin_1",
        change=ToolSettingChange(
            tool_name="query_cmdb",
            changed_by="admin_1",
            source="tool",
            before=None,
            after={"enabled": False, "roles": None},
        ),
    )
    rows = await store.history("query_cmdb")
    assert len(rows) == 1
    assert rows[0].changed_by == "admin_1"
    assert rows[0].source == "tool"
    assert rows[0].before is None
    assert rows[0].after == {"enabled": False, "roles": None}

    await store.replace(
        {
            "query_cmdb": ToolOverride(roles=("admin",)),
            "create_ticket": ToolOverride(enabled=False),
        },
        updated_by="admin_2",
        changes=[
            ToolSettingChange(
                tool_name="query_cmdb",
                changed_by="admin_2",
                source="matrix",
                before={"enabled": False, "roles": None},
                after={"enabled": None, "roles": ["admin"]},
            ),
            ToolSettingChange(
                tool_name="create_ticket",
                changed_by="admin_2",
                source="matrix",
                before=None,
                after={"enabled": False, "roles": None},
            ),
        ],
    )
    rows = await store.history("query_cmdb")
    assert [row.changed_by for row in rows] == ["admin_2", "admin_1"]
    assert len(await store.history("query_cmdb", limit=1)) == 1
    # 同一事务的 now() 让同一次矩阵提交共享时间戳
    assert (await store.history("create_ticket"))[0].changed_at == rows[0].changed_at


async def test_history_is_scoped_per_tool(pg_tool_history: PostgresToolSettingStore) -> None:
    store = pg_tool_history
    await store.upsert(
        "query_cmdb",
        ToolOverride(enabled=False),
        updated_by="admin_1",
        change=ToolSettingChange(
            tool_name="query_cmdb",
            changed_by="admin_1",
            source="tool",
            before=None,
            after={"enabled": False, "roles": None},
        ),
    )
    await store.upsert(
        "create_ticket",
        ToolOverride(enabled=False),
        updated_by="admin_1",
        change=ToolSettingChange(
            tool_name="create_ticket",
            changed_by="admin_1",
            source="tool",
            before=None,
            after={"enabled": False, "roles": None},
        ),
    )
    assert len(await store.history("query_cmdb")) == 1
    assert len(await store.history("create_ticket")) == 1
    assert await store.history("ghost") == []
