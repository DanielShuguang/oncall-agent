"""Postgres 用户预算覆盖存储（ADR-0026，默认跳过）。

只验证存取契约与列约束；预算闸门本身在 `test_budgets.py` 用内存实现覆盖，
不需要每个用例都连库。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.budgets.store import PostgresUserBudgetStore
from app.models import Base


@pytest_asyncio.fixture
async def pg_user_budgets() -> AsyncIterator[
    tuple[PostgresUserBudgetStore, async_sessionmaker[AsyncSession]]
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
        yield PostgresUserBudgetStore(sessionmaker), sessionmaker
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_upsert_load_and_delete(
    pg_user_budgets: tuple[PostgresUserBudgetStore, async_sessionmaker[AsyncSession]],
) -> None:
    store, _ = pg_user_budgets
    await store.upsert("u_205", 120, updated_by="admin_1")
    loaded = await store.load()
    assert loaded["u_205"].daily_cents == 120
    assert loaded["u_205"].updated_by == "admin_1"
    assert loaded["u_205"].updated_at is not None

    # 覆盖是 upsert：同一用户只留一行，修改人跟着变
    await store.upsert("u_205", 0, updated_by="admin_2")
    loaded = await store.load()
    assert len(loaded) == 1
    assert loaded["u_205"].daily_cents == 0
    assert loaded["u_205"].updated_by == "admin_2"

    await store.delete("u_205")
    assert await store.load() == {}


async def test_daily_cents_must_be_non_negative(
    pg_user_budgets: tuple[PostgresUserBudgetStore, async_sessionmaker[AsyncSession]],
) -> None:
    """0 是合法值（显式不限），负数由 CHECK 兜底。"""
    store, sessionmaker = pg_user_budgets
    await store.upsert("u_1", 0, updated_by="admin_1")
    assert (await store.load())["u_1"].daily_cents == 0

    with pytest.raises(IntegrityError):
        async with sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO user_budgets (user_id, daily_cents, updated_by) "
                    "VALUES ('u_bad', -1, 'admin_1')"
                )
            )
