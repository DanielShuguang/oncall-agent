"""RunStore 契约测试：内存实现与 Postgres 实现必须表现一致。

Postgres 部分默认跳过；设置 ONCALL_TEST_DATABASE_URL 指到一个**空库**后运行。
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

    # 幂等键按用户作用域：不同用户撞 key 不能互相回放
    other_user, created_other = await store.create(
        run_id=str(uuid.uuid4()),
        user_id="u_201",
        session_id="sess_1",
        message="另一个用户",
        client_msg_id="cmsg_1",
    )
    assert created_other is True
    assert other_user.run_id != run_id

    # 空串按“未提供”处理：不能变成共享的 "" 幂等键，也不能第二次提交时 500
    blank_a, created_blank_a = await store.create(
        run_id=str(uuid.uuid4()),
        user_id="u_102",
        session_id="sess_1",
        message="空 key A",
        client_msg_id="",
    )
    blank_b, created_blank_b = await store.create(
        run_id=str(uuid.uuid4()),
        user_id="u_102",
        session_id="sess_1",
        message="空 key B",
        client_msg_id="",
    )
    assert created_blank_a is True
    assert created_blank_b is True
    assert blank_a.run_id != blank_b.run_id

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
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.step_count == 1  # 失败 run 也要有步数口径
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

    # 终态不能被断连收尾覆盖（run.completed 后客户端断开很常见）
    await store.set_status(run_id, RunStatus.INTERRUPTED.value)
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.COMPLETED.value
    assert rec.finished_at is not None

    # 非终态仍然可以被标记为 interrupted
    interrupted_id = str(uuid.uuid4())
    await store.create(run_id=interrupted_id, user_id="u_102", session_id="sess_2", message="断线")
    await store.append(interrupted_id, EventType.RUN_STARTED, {})
    await store.set_status(interrupted_id, RunStatus.INTERRUPTED.value)
    interrupted = await store.get(interrupted_id)
    assert interrupted is not None
    assert interrupted.status == RunStatus.INTERRUPTED.value
    assert interrupted.finished_at is not None

    # 失败的 run 也保留 step_count
    failed_id = str(uuid.uuid4())
    await store.create(run_id=failed_id, user_id="u_102", session_id="sess_3", message="失败")
    await store.append(failed_id, EventType.RUN_STARTED, {})
    await store.append(failed_id, EventType.STEP_COMPLETED, {"node": "intake"})
    await store.append(failed_id, EventType.STEP_COMPLETED, {"node": "classify"})
    await store.append(failed_id, EventType.RUN_FAILED, {"error_code": "MODEL_TIMEOUT"})
    failed = await store.get(failed_id)
    assert failed is not None
    assert failed.status == RunStatus.FAILED.value
    assert failed.step_count == 2
    assert failed.error_code == "MODEL_TIMEOUT"
    assert failed.failure_category == "model"

    # 审批拒绝/超时也要有归因，不能等后续 run.failed 才补（事件投影自身要完整）
    rejected_id = str(uuid.uuid4())
    await store.create(run_id=rejected_id, user_id="u_102", session_id="sess_4", message="开单")
    await store.append(rejected_id, EventType.RUN_STARTED, {})
    await store.append(rejected_id, EventType.APPROVAL_RESOLVED, {"status": "rejected"})
    rejected = await store.get(rejected_id)
    assert rejected is not None
    assert rejected.status == RunStatus.FAILED.value
    assert rejected.failure_category == "approval"

    assert await store.status(run_id) == RunStatus.COMPLETED.value
    assert await store.status(str(uuid.uuid4())) is None
    assert await store.owner(run_id) == "u_102"
    assert await store.owner(str(uuid.uuid4())) is None

    # 多轮上下文（ADR-0020）：只取「有回答」的轮次，按时间正序，按用户 + 会话隔离
    second_id = str(uuid.uuid4())
    await store.create(run_id=second_id, user_id="u_102", session_id="sess_1", message="那怎么办？")
    await store.append(second_id, EventType.RUN_STARTED, {})
    await store.append(second_id, EventType.MESSAGE_COMPLETED, {"text": "先看重启后的日志"})
    await store.append(second_id, EventType.RUN_COMPLETED, {"status": "completed"})

    # 挂起审批的 run 没有 output：不能冒充"上一轮回答"
    pending_id = str(uuid.uuid4())
    await store.create(run_id=pending_id, user_id="u_102", session_id="sess_1", message="帮我开单")
    await store.append(pending_id, EventType.RUN_STARTED, {})
    await store.append(pending_id, EventType.APPROVAL_REQUIRED, {"approval_id": "apr_x"})

    # 同会话但别的用户：不能串到 u_102 的历史里
    other_user_run = str(uuid.uuid4())
    await store.create(
        run_id=other_user_run, user_id="u_999", session_id="sess_1", message="别人的问题"
    )
    await store.append(other_user_run, EventType.MESSAGE_COMPLETED, {"text": "别人的回答"})
    await store.append(other_user_run, EventType.RUN_COMPLETED, {})

    # 同用户但别的会话
    other_session_run = str(uuid.uuid4())
    await store.create(
        run_id=other_session_run, user_id="u_102", session_id="sess_other", message="别的会话"
    )
    await store.append(other_session_run, EventType.MESSAGE_COMPLETED, {"text": "别的回答"})
    await store.append(other_session_run, EventType.RUN_COMPLETED, {})

    turns = await store.recent_turns(user_id="u_102", session_id="sess_1")
    assert [(turn.query, turn.answer) for turn in turns] == [
        ("我电脑连不上打印机了", "先重启 Print Spooler"),
        ("那怎么办？", "先看重启后的日志"),
    ]
    latest = await store.recent_turns(user_id="u_102", session_id="sess_1", limit=1)
    assert [turn.query for turn in latest] == ["那怎么办？"]
    assert [
        turn.query
        for turn in await store.recent_turns(
            user_id="u_102", session_id="sess_1", exclude_run_id=second_id
        )
    ] == ["我电脑连不上打印机了"]
    assert [
        turn.query for turn in await store.recent_turns(user_id="u_102", session_id="sess_other")
    ] == ["别的会话"]
    assert [
        turn.query for turn in await store.recent_turns(user_id="u_999", session_id="sess_1")
    ] == ["别人的问题"]


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


async def _exercise_stale(store: RunStore) -> None:
    # 以操作前的时刻为界：之后创建的事件都晚于 now，不会被误判为过期
    now = datetime.now(UTC)
    stale_id = str(uuid.uuid4())
    await store.create(run_id=stale_id, user_id="u_302", session_id="sess_stale", message="崩溃")
    await store.append(stale_id, EventType.RUN_STARTED, {})

    fresh_id = str(uuid.uuid4())
    await store.create(run_id=fresh_id, user_id="u_302", session_id="sess_stale", message="正常")
    await store.append(fresh_id, EventType.RUN_STARTED, {})

    # 阈值取操作前：这两个 run 都不该被判定为过期
    recent_ids = {item.run_id for item in await store.list_stale_runs(older_than=now)}
    assert stale_id not in recent_ids
    assert fresh_id not in recent_ids
    assert not await store.fail_stale_run(fresh_id, older_than=now, payload={})

    # 全新 run 也能被识别（没有事件时回退到 started_at）
    silent_id = str(uuid.uuid4())
    await store.create(run_id=silent_id, user_id="u_302", session_id="sess_stale", message="没事件")

    future = now + timedelta(minutes=11)
    stale_ids = {item.run_id for item in await store.list_stale_runs(older_than=future)}
    assert {stale_id, fresh_id, silent_id} <= stale_ids
    assert not await store.fail_stale_run(str(uuid.uuid4()), older_than=future, payload={})
    assert not await store.fail_stale_run("not-a-uuid", older_than=future, payload={})

    payload = {"error_code": "RUN_INTERRUPTED", "message": "进程中断"}
    assert await store.fail_stale_run(stale_id, older_than=future, payload=payload) is True
    rec = await store.get(stale_id)
    assert rec is not None
    assert rec.status == RunStatus.FAILED.value
    assert rec.error_code == "RUN_INTERRUPTED"
    assert rec.finished_at is not None
    events = await store.events_after(stale_id)
    assert [event.type for event in events] == [EventType.RUN_STARTED, EventType.RUN_FAILED]
    assert events[-1].payload["message"] == "进程中断"

    # 已是终态：重复回收不追加第二条 run.failed
    assert await store.fail_stale_run(stale_id, older_than=future, payload=payload) is False
    assert len(await store.events_after(stale_id)) == 2
    remaining = {item.run_id for item in await store.list_stale_runs(older_than=future)}
    assert stale_id not in remaining


async def test_memory_store_contract() -> None:
    store = InMemoryRunStore()
    await _exercise(store)
    await _exercise_concurrent_seq(store)
    await _exercise_stale(store)


@pytest_asyncio.fixture
async def pg_store() -> AsyncIterator[PostgresRunStore]:
    url = os.environ.get("ONCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 ONCALL_TEST_DATABASE_URL 指向一个可清空的测试库")

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        # 测试库需要 pgvector 类型；扩展是库级对象，drop_all 不会删它
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


async def test_postgres_store_contract(pg_store: PostgresRunStore) -> None:
    await _exercise(pg_store)
    await _exercise_concurrent_seq(pg_store)
    await _exercise_stale(pg_store)
