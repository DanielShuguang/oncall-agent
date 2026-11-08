"""RunStore 契约测试：内存实现与 Postgres 实现必须表现一致。

Postgres 部分默认跳过；设置 ONCALL_TEST_DATABASE_URL 指到一个**空库**后运行。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.store import InMemoryRunStore, PostgresRunStore, RunNotFoundError, RunStore
from app.models import Base
from app.schemas.event import EventType, RunStatus


async def _exercise(store: RunStore) -> None:
    run_id = str(uuid.uuid4())
    rec, created = await store.create(
        run_id=run_id,
        user_id="u_102",
        session_id="sess_1",
        message="我电脑连不上打印机了",
        client_msg_id="cmsg_1",
        max_steps=8,
    )
    assert created is True
    assert rec.run_id == run_id
    assert rec.status == RunStatus.RUNNING.value
    assert rec.input == "我电脑连不上打印机了"

    # 幂等：客户端重试不产生第二个 run
    dup, created_again = await store.create(
        run_id=str(uuid.uuid4()),
        user_id="u_102",
        session_id="sess_1",
        message="我电脑连不上打印机了",
        client_msg_id="cmsg_1",
    )
    assert created_again is False
    assert dup.run_id == run_id

    started = await store.append(
        run_id, EventType.RUN_STARTED, {"model": "mock-qwen2.5", "max_steps": 10}
    )
    assert started.seq == 1
    assert started.run_id == run_id

    # run.started 的 model/max_steps 要投影到 runs
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.model == "mock-qwen2.5"
    assert rec.max_steps == 10

    await store.append(run_id, EventType.STEP_STARTED, {"node": "intake"})
    await store.append(run_id, EventType.STEP_COMPLETED, {"node": "intake", "duration_ms": 5})
    await store.append(run_id, EventType.TOOL_CALL, {"tool": "query_cmdb"})
    await store.append(run_id, EventType.TOOL_RESULT, {"tool": "query_cmdb", "status": "ok"})
    await store.append(run_id, EventType.APPROVAL_REQUIRED, {"approval_id": "apr_1"})

    rec = await store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.AWAITING_APPROVAL.value
    assert rec.event_count == 6

    approved = await store.append(
        run_id, EventType.APPROVAL_RESOLVED, {"approval_id": "apr_1", "status": "approved"}
    )
    assert approved.seq == 7
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.RUNNING.value

    await store.append(run_id, EventType.MESSAGE_COMPLETED, {"text": "先重启 Print Spooler"})
    await store.append(
        run_id,
        EventType.RUN_COMPLETED,
        {"status": "completed", "steps": 6, "token_in": 100, "token_out": 20, "cost_cents": 3},
    )

    rec = await store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.COMPLETED.value
    assert rec.output == "先重启 Print Spooler"
    assert (rec.step_count, rec.token_in, rec.token_out, rec.cost_cents) == (6, 100, 20, 3)
    assert rec.finished_at is not None
    assert rec.event_count == 9

    # 续传语义：after_seq 严格大于；limit 生效
    all_events = await store.events_after(run_id)
    assert [e.seq for e in all_events] == list(range(1, 10))
    tail = await store.events_after(run_id, after_seq=7)
    assert [e.seq for e in tail] == [8, 9]
    assert [e.type for e in tail] == [
        EventType.MESSAGE_COMPLETED,
        EventType.RUN_COMPLETED,
    ]
    limited = await store.events_after(run_id, after_seq=0, limit=3)
    assert [e.seq for e in limited] == [1, 2, 3]

    # 未知 run 不能静默成功
    with pytest.raises(RunNotFoundError):
        await store.append(str(uuid.uuid4()), EventType.HEARTBEAT, {})
    assert await store.get(str(uuid.uuid4())) is None
    assert await store.events_after(str(uuid.uuid4())) == []

    # 断连标记
    await store.set_status(run_id, RunStatus.INTERRUPTED.value)
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.INTERRUPTED.value


async def _exercise_concurrent_seq(store: RunStore) -> None:
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_1", session_id="s", message="并发")
    events = await asyncio.gather(
        *(store.append(run_id, EventType.HEARTBEAT, {"i": i}) for i in range(10))
    )
    assert sorted(e.seq for e in events) == list(range(1, 11))

    rec = await store.get(run_id)
    assert rec is not None
    assert rec.event_count == 10


async def test_memory_store_contract() -> None:
    await _exercise(InMemoryRunStore())
    await _exercise_concurrent_seq(InMemoryRunStore())


@pytest_asyncio.fixture
async def pg_store() -> AsyncIterator[PostgresRunStore]:
    url = os.environ.get("ONCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 ONCALL_TEST_DATABASE_URL 指向一个可清空的测试库")

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield PostgresRunStore(sessionmaker)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_postgres_store_contract(pg_store: PostgresRunStore) -> None:
    await _exercise(pg_store)
    await _exercise_concurrent_seq(pg_store)
