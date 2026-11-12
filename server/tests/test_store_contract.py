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

from app.core.store import (
    InMemoryRunStore,
    PostgresRunStore,
    PrunedContents,
    PrunedEvents,
    RunNotFoundError,
    RunStore,
)
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

    # 列表的事件条数必须和详情一致（内存靠 append 维护，Postgres 靠聚合）
    listed = {item.run_id: item for item in await store.list_runs(user_id="u_102", limit=20)}
    assert listed[run_id].event_count == 9

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

    # 纯空白的 output 不算「有回答」：内存用 .strip()，Postgres 用 regexp_replace 去空白
    # （btrim 默认只去空格，不去换行/制表符），两端口径必须一致
    blank_answer_id = str(uuid.uuid4())
    await store.create(
        run_id=blank_answer_id, user_id="u_102", session_id="sess_ws", message="空白回答"
    )
    await store.append(blank_answer_id, EventType.MESSAGE_COMPLETED, {"text": "  \n\t "})
    await store.append(blank_answer_id, EventType.RUN_COMPLETED, {})
    assert await store.recent_turns(user_id="u_102", session_id="sess_ws") == []


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


async def _exercise_prune(store: RunStore) -> None:
    """保留清理（ADR-0021）：按 run 整场删、dry-run 不动、标记后不重复清。"""
    not_yet = datetime.now(UTC) - timedelta(days=1)

    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_304", session_id="sess_prune", message="打印机")
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock"})
    await store.append(run_id, EventType.MESSAGE_COMPLETED, {"text": "重启打印服务"})
    await store.append(run_id, EventType.RUN_COMPLETED, {"status": "completed"})

    # 还没到保留期：不能动
    assert await store.prune_events(finished_before=not_yet) == PrunedEvents(run_ids=[])

    future = datetime.now(UTC) + timedelta(days=365)
    preview = await store.prune_events(finished_before=future, dry_run=True)
    assert run_id in preview.run_ids
    assert preview.deleted == 0
    assert len(await store.events_after(run_id)) == 3

    pruned = await store.prune_events(finished_before=future)
    assert run_id in pruned.run_ids
    assert pruned.deleted >= 3
    assert await store.events_after(run_id) == []
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.events_pruned_at is not None
    assert rec.event_count == 0
    listed = {item.run_id: item for item in await store.list_runs(user_id="u_304", limit=20)}
    assert listed[run_id].event_count == 0
    # 事件删了，多轮上下文仍可读（ADR-0020 只读 runs.input/output）
    assert [
        (turn.query, turn.answer)
        for turn in await store.recent_turns(user_id="u_304", session_id="sess_prune")
    ] == [("打印机", "重启打印服务")]

    # 已经清理过：不会再被选中（多副本/多轮扫描是幂等的）
    again = await store.prune_events(finished_before=future)
    assert run_id not in again.run_ids


async def _exercise_prune_contents(store: RunStore) -> None:
    """正文按时间清理（ADR-0023）：清空 input/output、留标记，摘要与列表照旧。"""
    not_yet = datetime.now(UTC) - timedelta(days=1)
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id, user_id="u_306", session_id="sess_content", message="打印机坏了"
    )
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock"})
    await store.append(
        run_id,
        EventType.MESSAGE_COMPLETED,
        {"text": "重启打印服务", "citations": [{"document_id": "doc_x", "title": "打印机"}]},
    )
    await store.append(run_id, EventType.RUN_COMPLETED, {"status": "completed"})

    # 还没到保留期：正文不能动
    assert await store.prune_contents(finished_before=not_yet) == PrunedContents(run_ids=[])

    future = datetime.now(UTC) + timedelta(days=365)
    preview = await store.prune_contents(finished_before=future, dry_run=True)
    assert run_id in preview.run_ids
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.output == "重启打印服务"
    assert rec.content_pruned_at is None
    # 引用快照（ADR-0031）：角标字段在，事件清了也能回放
    assert rec.citations == [
        {"chunk_id": 0, "document_id": "doc_x", "ord": 0, "title": "打印机", "snippet": ""}
    ]

    pruned = await store.prune_contents(finished_before=future)
    assert run_id in pruned.run_ids
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.input == ""
    assert rec.output is None
    assert rec.content_pruned_at is not None
    # `cited_document_ids` 是元数据，不随正文清理：详情仍能解释「这场引用过什么」
    assert rec.cited_document_ids == ["doc_x"]
    # 但引用片段属于回答内容：正文清空时快照一并清掉（ADR-0031）
    assert rec.citations == []
    # 回放读路径一次取到「引用快照 + 已过期」，不用再查知识库
    state = await store.content_state(run_id)
    assert state is not None
    assert state.content_pruned_at is not None
    # 摘要与列表照常：状态、计量、事件清理标记都不受影响
    assert rec.status == RunStatus.COMPLETED.value
    assert rec.events_pruned_at is None
    listed = {item.run_id: item for item in await store.list_runs(user_id="u_306", limit=20)}
    assert listed[run_id].content_pruned_at is not None
    # 多轮历史只认 output 非空：清空后这一轮不再进上下文
    assert await store.recent_turns(user_id="u_306", session_id="sess_content") == []

    # 幂等：标记写入后不再入选
    again = await store.prune_contents(finished_before=future)
    assert run_id not in again.run_ids


async def _exercise_cited_documents(store: RunStore) -> None:
    """引用快照（ADR-0022）：`message.completed.citations` 投影到 runs，事件清了也还在。"""
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id, user_id="u_305", session_id="sess_cite", message="年终奖什么时候发"
    )
    state = await store.content_state(run_id)
    assert state is not None
    assert state.cited_document_ids == []
    assert state.content_pruned_at is None

    # 没有 citations 字段的事件不改字段（旧客户端/拒答都没有引用）
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock"})
    await store.append(run_id, EventType.MESSAGE_COMPLETED, {"text": "1 月发"})
    state = await store.content_state(run_id)
    assert state is not None and state.cited_document_ids == []

    # 去重保序；非字符串/空 id/非对象元素忽略
    await store.append(
        run_id,
        EventType.MESSAGE_COMPLETED,
        {
            "text": "年终奖 1 月随工资发放",
            "citations": [
                {"document_id": "doc_b", "title": "薪酬"},
                {"document_id": "doc_a", "chunk_id": 7},
                {"document_id": "doc_b"},
                {"document_id": ""},
                {"title": "没有 document_id"},
                "不是对象",
            ],
        },
    )
    state = await store.content_state(run_id)
    assert state is not None
    assert state.cited_document_ids == ["doc_b", "doc_a"]
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.cited_document_ids == ["doc_b", "doc_a"]
    # 多轮历史也带着引用快照，供读时过滤（ADR-0022）
    turns = await store.recent_turns(user_id="u_305", session_id="sess_cite")
    assert [turn.cited_document_ids for turn in turns] == [("doc_b", "doc_a")]

    # 空数组表示「这轮明确没有引用」：以最后一次回答为准，不能残留旧引用
    await store.append(
        run_id,
        EventType.MESSAGE_COMPLETED,
        {"text": "另一版回答", "citations": []},
    )
    state = await store.content_state(run_id)
    assert state is not None and state.cited_document_ids == []

    # 不存在的 run 返回 None（路由层据此 404），不是空数组
    assert await store.content_state(str(uuid.uuid4())) is None


async def _exercise_sessions(store: RunStore) -> None:
    """会话聚合（ADR-0030）：会话是 runs 的投影，按最近活动倒序，标题取最早非空输入。"""
    user = "u_sessions"
    other = "u_sessions_other"
    await store.create(
        run_id=str(uuid.uuid4()), user_id=user, session_id="sess_a", message="打印机离线"
    )
    await store.create(
        run_id=str(uuid.uuid4()), user_id=user, session_id="sess_a", message="还是不行"
    )
    await asyncio.sleep(0.005)
    second = str(uuid.uuid4())
    await store.create(run_id=second, user_id=user, session_id="sess_b", message="VPN 掉线")
    # 首条输入是空白时跳过，标题落到下一条；只有空白输入的会话标题为 None，但会话本身仍在
    await store.create(run_id=str(uuid.uuid4()), user_id=user, session_id="sess_c", message="   ")
    await store.create(
        run_id=str(uuid.uuid4()), user_id=user, session_id="sess_c", message="真实问题"
    )
    await store.create(run_id=str(uuid.uuid4()), user_id=other, session_id="sess_x", message="别人")

    sessions = await store.list_sessions(user_id=user, limit=10)
    by_id = {item.session_id: item for item in sessions}
    assert set(by_id) == {"sess_a", "sess_b", "sess_c"}
    assert by_id["sess_a"].title == "打印机离线"
    assert by_id["sess_a"].run_count == 2
    assert by_id["sess_c"].title == "真实问题"
    assert by_id["sess_c"].run_count == 2
    # 最近活动的会话在前；sess_x 属于别人，不能出现
    assert sessions[0].session_id in {"sess_c", "sess_b"}
    assert "sess_x" not in by_id

    # limit 截断的是「会话」而不是 run；keyset 游标能取到下一页（ADR-0033）
    limited = await store.list_sessions(user_id=user, limit=1)
    assert len(limited) == 1
    assert limited[0].session_id == "sess_c"

    first_page = await store.list_sessions(user_id=user, limit=2)
    assert [item.session_id for item in first_page] == ["sess_c", "sess_b"]
    older = await store.list_sessions(
        user_id=user,
        limit=2,
        before_updated_at=first_page[-1].updated_at,
        before_session_id=first_page[-1].session_id,
    )
    assert [item.session_id for item in older] == ["sess_a"]

    # 按标题搜索（ADR-0039）：大小写不敏感、只匹配投影标题、不越权
    searched = await store.list_sessions(user_id=user, limit=10, query="打印机")
    assert [item.session_id for item in searched] == ["sess_a"]
    assert [
        item.session_id for item in await store.list_sessions(user_id=user, limit=10, query="真实")
    ] == ["sess_c"]
    # PG 的 lower() 也要覆盖 ASCII 大小写，而不只是中文子串
    assert [
        item.session_id for item in await store.list_sessions(user_id=user, limit=10, query="vpn")
    ] == ["sess_b"]
    assert await store.list_sessions(user_id=user, limit=10, query="不存在") == []
    assert await store.list_sessions(user_id=user, limit=10, query="别人") == []
    assert await store.list_sessions(user_id=other, limit=10, query="打印机") == []

    # 按会话过滤 run：own-only，且不返回其他会话
    runs = await store.list_runs(user_id=user, session_id="sess_a", limit=10)
    assert {item.session_id for item in runs} == {"sess_a"}
    assert {item.input for item in runs} == {"打印机离线", "还是不行"}
    assert await store.list_runs(user_id=user, session_id="sess_missing", limit=10) == []
    other_runs = await store.list_runs(user_id=other, session_id="sess_a", limit=10)
    assert other_runs == []


async def _exercise_events_for_runs(store: RunStore) -> None:
    """批量取事件（ADR-0036）：按 run 分组、组内 seq 升序、每个 run 独立截断。"""
    user = "u_events_batch"
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    await store.create(run_id=first, user_id=user, session_id="sess_events", message="第一轮")
    await store.create(run_id=second, user_id=user, session_id="sess_events", message="第二轮")
    for node in ("intake", "retrieve", "finalize"):
        await store.append(first, EventType.STEP_STARTED, {"node": node})
    for node in ("intake", "retrieve"):
        await store.append(second, EventType.STEP_STARTED, {"node": node})

    grouped = await store.events_for_runs([first, second, str(uuid.uuid4())])
    assert set(grouped) == {first, second}
    assert [event.seq for event in grouped[first]] == [1, 2, 3]
    assert [event.seq for event in grouped[second]] == [1, 2]
    assert [event.payload["node"] for event in grouped[first]] == [
        "intake",
        "retrieve",
        "finalize",
    ]

    limited = await store.events_for_runs([first, second], limit_per_run=1)
    assert [event.seq for event in limited[first]] == [1]
    assert [event.seq for event in limited[second]] == [1]
    assert await store.events_for_runs([]) == {}
    assert await store.events_for_runs(["not-a-uuid"]) == {}


async def test_memory_store_contract() -> None:
    store = InMemoryRunStore()
    await _exercise(store)
    await _exercise_concurrent_seq(store)
    await _exercise_stale(store)
    await _exercise_prune(store)
    await _exercise_prune_contents(store)
    await _exercise_cited_documents(store)
    await _exercise_sessions(store)
    await _exercise_events_for_runs(store)


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
    await _exercise_prune(pg_store)
    await _exercise_prune_contents(pg_store)
    await _exercise_cited_documents(pg_store)
    await _exercise_sessions(pg_store)
    await _exercise_events_for_runs(pg_store)
