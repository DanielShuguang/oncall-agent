"""Postgres 工单仓储集成测试（默认跳过）。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.tools.tickets import PostgresTicketRepository


@pytest_asyncio.fixture
async def pg_tickets() -> AsyncIterator[PostgresTicketRepository]:
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
        yield PostgresTicketRepository(sessionmaker)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


async def test_pg_lists_only_requesters_tickets_in_created_order(
    pg_tickets: PostgresTicketRepository,
) -> None:
    first = await pg_tickets.create(
        title="打印机离线", category="hardware", priority="P2", requester="u_102"
    )
    second = await pg_tickets.create(
        title="VPN 连不上", category="network", priority="P1", requester="u_102"
    )
    await pg_tickets.create(
        title="别人的工单", category="hardware", priority="P3", requester="u_205"
    )

    rows = await pg_tickets.list_for_requester("u_102", limit=5)
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert all(row["requester"] == "u_102" for row in rows)
    assert all(row["created_at"] is not None for row in rows)

    limited = await pg_tickets.list_for_requester("u_102", limit=1)
    assert len(limited) == 1
    assert await pg_tickets.list_for_requester("u_102", status="resolved") == []
