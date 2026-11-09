"""孤儿 run 回收（ADR-0017）。

进程崩溃后停在 running 的 run 必须能收敛到终态；但回收**不能**重放写工具。
这里覆盖内存后端的策略层：阈值、dry-run、审批等待中的 run 不归它管。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.store import InMemoryRunStore
from app.runs.recovery import ERROR_CODE, RunRecovery, interrupted_payload
from app.schemas.event import EventType, RunStatus


def _recovery(store: InMemoryRunStore) -> RunRecovery:
    # 显式阈值：本机 .env 若覆盖 ONCALL_STALE_RUN_MIN，用例不能跟着漂
    return RunRecovery(store, settings=Settings(env="dev", stale_run_min=10))


async def _running(store: InMemoryRunStore) -> str:
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_402", session_id="sess_reap", message="长任务")
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock-qwen2.5"})
    return run_id


async def test_reap_fails_stale_running_run() -> None:
    store = InMemoryRunStore()
    run_id = await _running(store)

    result = await _recovery(store).reap(now=datetime.now(UTC) + timedelta(minutes=11))

    assert result.scanned == 1
    assert result.reaped == [run_id]
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.FAILED.value
    assert rec.error_code == ERROR_CODE
    assert rec.failure_category == "internal"
    assert rec.finished_at is not None
    events = await store.events_after(run_id)
    assert events[-1].type is EventType.RUN_FAILED
    assert events[-1].payload["error_code"] == ERROR_CODE
    assert "请人工确认后重新发起" in events[-1].payload["message"]


async def test_new_run_is_not_reaped() -> None:
    store = InMemoryRunStore()
    run_id = await _running(store)

    result = await _recovery(store).reap(now=datetime.now(UTC))

    assert result.scanned == 0
    assert result.reaped == []
    assert (await store.status(run_id)) == RunStatus.RUNNING.value


async def test_dry_run_lists_without_writing() -> None:
    store = InMemoryRunStore()
    run_id = await _running(store)

    result = await _recovery(store).reap(
        now=datetime.now(UTC) + timedelta(minutes=11), dry_run=True
    )

    assert result.dry_run is True
    assert result.reaped == [run_id]
    assert (await store.status(run_id)) == RunStatus.RUNNING.value
    assert len(await store.events_after(run_id)) == 1


async def test_awaiting_approval_is_left_to_ttl_sweeper() -> None:
    """审批等待中的 run 由 approvals TTL 回收，不能被当成孤儿直接 failed。"""
    store = InMemoryRunStore()
    run_id = await _running(store)
    await store.append(run_id, EventType.APPROVAL_REQUIRED, {"approval_id": "apr_1"})

    result = await _recovery(store).reap(now=datetime.now(UTC) + timedelta(minutes=11))

    assert result.reaped == []
    assert (await store.status(run_id)) == RunStatus.AWAITING_APPROVAL.value


async def test_reap_is_idempotent() -> None:
    store = InMemoryRunStore()
    run_id = await _running(store)
    recovery = _recovery(store)
    future = datetime.now(UTC) + timedelta(minutes=11)

    first = await recovery.reap(now=future)
    second = await recovery.reap(now=future)

    assert first.reaped == [run_id]
    assert second.reaped == []
    assert len(await store.events_after(run_id)) == 2


async def test_completed_run_is_not_reaped() -> None:
    store = InMemoryRunStore()
    run_id = await _running(store)
    await store.append(run_id, EventType.RUN_COMPLETED, {"status": "completed"})

    result = await _recovery(store).reap(now=datetime.now(UTC) + timedelta(minutes=11))

    assert result.reaped == []
    assert (await store.status(run_id)) == RunStatus.COMPLETED.value
    assert len(await store.events_after(run_id)) == 2


async def test_run_without_events_uses_started_at() -> None:
    """建完 run、还没写 run.started 就崩了：也要能收敛。"""
    store = InMemoryRunStore()
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_402", session_id="sess_reap", message="刚建就崩")

    result = await _recovery(store).reap(now=datetime.now(UTC) + timedelta(minutes=11))

    assert result.reaped == [run_id]
    events = await store.events_after(run_id)
    assert [event.type for event in events] == [EventType.RUN_FAILED]
    assert events[0].seq == 1


async def test_last_event_wins_over_old_started_at() -> None:
    """run 创建很久但一直有事件：按最后活动时间判断，不能因为 started_at 老就杀掉。"""
    store = InMemoryRunStore()
    run_id = await _running(store)
    rec = await store.get(run_id)
    assert rec is not None
    rec.started_at = datetime.now(UTC) - timedelta(hours=2)

    result = await _recovery(store).reap(now=datetime.now(UTC))

    assert result.scanned == 0
    assert (await store.status(run_id)) == RunStatus.RUNNING.value


async def test_reap_respects_limit() -> None:
    store = InMemoryRunStore()
    first = await _running(store)
    second = await _running(store)
    now = datetime.now(UTC) + timedelta(minutes=11)

    result = await _recovery(store).reap(now=now, limit=1)

    assert result.scanned == 1
    assert len(result.reaped) == 1
    left = ({first, second} - set(result.reaped)).pop()
    rec = await store.get(left)
    assert rec is not None and rec.status == RunStatus.RUNNING.value
    # 下一次扫描再处理剩下的那个
    rest = await _recovery(store).reap(now=now, limit=1)
    assert rest.reaped == [left]


def test_interrupted_payload_documents_no_auto_retry() -> None:
    payload = interrupted_payload(10)
    assert payload["error_code"] == ERROR_CODE
    assert payload["category"] == "internal"
    assert payload["at_step"] == 0
    assert "10 分钟" in payload["message"]
    assert "不会自动重试" in payload["message"]
