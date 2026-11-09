"""Postgres 孤儿 run 回收测试（默认跳过）。

只验证内存后端模拟不了的部分：多个副本同时回收同一个 run 时，
行锁 + 事务内条件检查保证只有一方写入 `run.failed`（ADR-0017）。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.store import PostgresRunStore
from app.models import Base
from app.runs.recovery import interrupted_payload
from app.schemas.event import EventType


@pytest_asyncio.fixture
async def pg_store() -> AsyncIterator[PostgresRunStore]:
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
        yield PostgresRunStore(sessionmaker)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_concurrent_reap_writes_failure_once(pg_store: PostgresRunStore) -> None:
    run_id = str(uuid.uuid4())
    await pg_store.create(run_id=run_id, user_id="u_402", session_id="sess_pg", message="崩溃")
    await pg_store.append(run_id, EventType.RUN_STARTED, {})

    older_than = datetime.now(UTC) + timedelta(minutes=11)
    payload = interrupted_payload(10)
    results = await asyncio.gather(
        pg_store.fail_stale_run(run_id, older_than=older_than, payload=payload),
        pg_store.fail_stale_run(run_id, older_than=older_than, payload=payload),
    )

    # 两个回收任务同时看到候选；只有先拿到行锁的一方真正迁移
    assert sorted(results) == [False, True]
    events = await pg_store.events_after(run_id)
    assert [event.type for event in events].count(EventType.RUN_FAILED) == 1
    rec = await pg_store.get(run_id)
    assert rec is not None
    assert rec.status == "failed"
    assert rec.error_code == "RUN_INTERRUPTED"
