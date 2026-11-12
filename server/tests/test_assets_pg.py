"""Postgres 资产仓储集成测试（默认跳过）。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.models.business import Asset
from app.tools.assets import PostgresAssetRepository


@pytest_asyncio.fixture
async def pg_assets() -> AsyncIterator[tuple[PostgresAssetRepository, async_sessionmaker]]:
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
        yield PostgresAssetRepository(sessionmaker), sessionmaker
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


async def test_pg_query_cmdb_reads_assets_table_and_owner_is_scoped(
    pg_assets: tuple[PostgresAssetRepository, async_sessionmaker],
) -> None:
    repo, sessionmaker = pg_assets
    async with sessionmaker() as session:
        session.add_all(
            [
                Asset(
                    id="PC-20481",
                    owner_id="u_102",
                    type="laptop",
                    model="ThinkPad T14",
                    location="3F-东区",
                    ip="10.20.31.44",
                    warranty_to=date(2027, 3, 31),
                    status="online",
                ),
                Asset(
                    id="PC-20499",
                    owner_id="u_102",
                    type="monitor",
                    model="Dell U2723QE",
                    status="online",
                ),
                Asset(id="PC-20517", owner_id="u_205", type="laptop", model="MacBook Pro 14"),
            ]
        )
        await session.commit()

    rows = await repo.list_for_owner("u_102")
    assert [row["asset_id"] for row in rows] == ["PC-20481", "PC-20499"]
    assert all(row["owner_id"] == "u_102" for row in rows)
    assert rows[0]["warranty_until"] == "2027-03-31"
    assert rows[1]["warranty_until"] is None

    limited = await repo.list_for_owner("u_102", asset_id="PC-20499")
    assert [row["asset_id"] for row in limited] == ["PC-20499"]
    assert await repo.list_for_owner("u_205", asset_id="PC-20481") == []
