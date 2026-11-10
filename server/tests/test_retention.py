"""数据保留清理（ADR-0021）。

docs/02 §4 写了保留期，但在此之前只有配置项、没有执行者：事件与计量只增不删。
这里覆盖策略层：清理边界（只动终态、按 run 整场删）、dry-run、批次与幂等；
内存与 Postgres 的行为一致性由 `test_store_contract.py` 的共享契约保证。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.store import InMemoryRunStore
from app.gateway.meter import InMemoryModelCallStore, ModelCallRecord
from app.runs.retention import RetentionSweeper
from app.schemas.event import EventType, RunStatus


def _settings(**overrides: object) -> Settings:
    # 显式阈值：本机 .env 若覆盖保留天数，用例不能跟着漂。
    # 正文保留期比事件长（60 > 30）：既有用例验证「事件清了、摘要与回答还在」，
    # 这个差值本身就是那条规则的前提（ADR-0023 要求正文 >= 事件）
    base: dict[str, object] = {
        "env": "dev",
        "event_retention_days": 30,
        "model_call_retention_days": 90,
        "run_content_retention_days": 60,
        "retention_batch": 200,
    }
    base.update(overrides)
    return Settings(**base)


def _sweeper(
    store: InMemoryRunStore,
    calls: InMemoryModelCallStore | None = None,
    *,
    settings: Settings | None = None,
) -> RetentionSweeper:
    return RetentionSweeper(
        store,
        calls or InMemoryModelCallStore(),
        settings=settings or _settings(),
    )


async def _finished_run(
    store: InMemoryRunStore, *, user_id: str = "u_701", session_id: str = "sess_ret"
) -> str:
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id=user_id, session_id=session_id, message="打印不了")
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock"})
    await store.append(run_id, EventType.MESSAGE_COMPLETED, {"text": "重启打印服务"})
    await store.append(run_id, EventType.RUN_COMPLETED, {"status": "completed"})
    return run_id


async def _running_run(store: InMemoryRunStore) -> str:
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_701", session_id="sess_ret", message="长任务")
    await store.append(run_id, EventType.RUN_STARTED, {})
    return run_id


async def _call(
    calls: InMemoryModelCallStore,
    *,
    created_at: datetime,
    token_in: int = 100,
    run_id: str | None = None,
) -> None:
    await calls.record(
        ModelCallRecord(
            run_id=run_id or str(uuid.uuid4()),
            step="plan",
            provider="cloud",
            model="gpt-test",
            token_in=token_in,
            token_out=10,
            cost_cents=1,
            latency_ms=20,
            first_token_ms=None,
            status="ok",
            error=None,
            created_at=created_at,
        )
    )


async def test_prunes_expired_events_by_run() -> None:
    store = InMemoryRunStore()
    run_id = await _finished_run(store)

    result = await _sweeper(store).sweep(now=datetime.now(UTC) + timedelta(days=31))

    assert result.run_ids == [run_id]
    assert result.events == 3
    assert await store.events_after(run_id) == []
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.events_pruned_at is not None
    assert rec.event_count == 0
    # 摘要与回答保留：运行列表、成本口径、多轮上下文都还要用
    assert rec.output == "重启打印服务"
    assert rec.status == RunStatus.COMPLETED.value


async def test_recent_run_is_kept() -> None:
    store = InMemoryRunStore()
    run_id = await _finished_run(store)

    result = await _sweeper(store).sweep(now=datetime.now(UTC))

    assert result.run_ids == []
    assert len(await store.events_after(run_id)) == 3
    rec = await store.get(run_id)
    assert rec is not None and rec.events_pruned_at is None


async def test_non_terminal_runs_are_never_pruned() -> None:
    """等待审批的 run 可能长时间没有新事件；清理不能把它的审批上下文删掉。"""
    store = InMemoryRunStore()
    running_id = await _running_run(store)

    awaiting_id = str(uuid.uuid4())
    await store.create(
        run_id=awaiting_id, user_id="u_701", session_id="sess_ret", message="帮我开单"
    )
    await store.append(awaiting_id, EventType.RUN_STARTED, {})
    await store.append(awaiting_id, EventType.APPROVAL_REQUIRED, {"approval_id": "apr_1"})

    result = await _sweeper(store).sweep(now=datetime.now(UTC) + timedelta(days=365))

    assert result.run_ids == []
    assert len(await store.events_after(running_id)) == 1
    assert len(await store.events_after(awaiting_id)) == 2
    for run_id in (running_id, awaiting_id):
        rec = await store.get(run_id)
        assert rec is not None and rec.events_pruned_at is None


async def test_dry_run_reports_without_deleting() -> None:
    store = InMemoryRunStore()
    calls = InMemoryModelCallStore()
    run_id = await _finished_run(store)
    await _call(calls, created_at=datetime.now(UTC) - timedelta(days=200))
    future = datetime.now(UTC) + timedelta(days=31)

    result = await _sweeper(store, calls).sweep(now=future, dry_run=True)

    assert result.dry_run is True
    assert result.run_ids == [run_id]
    assert result.events == 0
    assert result.calls == 1
    assert len(await store.events_after(run_id)) == 3
    rec = await store.get(run_id)
    assert rec is not None and rec.events_pruned_at is None
    assert len(calls.records) == 1


async def test_prune_is_idempotent_and_batched() -> None:
    store = InMemoryRunStore()
    first = await _finished_run(store)
    second = await _finished_run(store)
    future = datetime.now(UTC) + timedelta(days=31)
    sweeper = _sweeper(store)

    # max_batches=1：这里验证的是「每轮只拿一批」的幂等，不是单轮排空
    one = await sweeper.sweep(now=future, limit=1, max_batches=1)
    two = await sweeper.sweep(now=future, limit=1, max_batches=1)
    three = await sweeper.sweep(now=future, limit=1, max_batches=1)

    assert len(one.run_ids) == 1
    assert len(two.run_ids) == 1
    assert one.run_ids[0] != two.run_ids[0]
    assert {one.run_ids[0], two.run_ids[0]} == {first, second}
    # 两场都已清完：第三轮没有候选，不会重复删
    assert three.run_ids == []
    assert three.events == 0


async def test_sweep_drains_batches_within_one_round() -> None:
    """默认单轮连续取批，直到取不满一批；否则 backlog 一大就永远追不上。"""
    store = InMemoryRunStore()
    run_ids = {await _finished_run(store) for _ in range(3)}
    future = datetime.now(UTC) + timedelta(days=31)

    result = await _sweeper(store).sweep(now=future, limit=1)

    assert set(result.run_ids) == run_ids
    assert result.events == 9
    assert result.capped is False
    for run_id in run_ids:
        rec = await store.get(run_id)
        assert rec is not None and rec.events_pruned_at is not None


async def test_sweep_respects_max_batches_and_continues_next_round() -> None:
    """批次上限让单次扫描的锁/事务量有上界，剩下的留给下一轮。"""
    store = InMemoryRunStore()
    run_ids = {await _finished_run(store) for _ in range(3)}
    future = datetime.now(UTC) + timedelta(days=31)
    sweeper = _sweeper(store)

    first = await sweeper.sweep(now=future, limit=1, max_batches=2)
    second = await sweeper.sweep(now=future, limit=1, max_batches=2)

    assert len(first.run_ids) == 2
    assert len(second.run_ids) == 1
    assert set(first.run_ids) | set(second.run_ids) == run_ids


async def test_sweep_marks_capped_when_batch_limit_hit() -> None:
    """跑满批次上限说明可能还有积压，调用方要能看见（日志 warning / CLI capped）。"""
    store = InMemoryRunStore()
    for _ in range(3):
        await _finished_run(store)
    future = datetime.now(UTC) + timedelta(days=31)
    sweeper = _sweeper(store)

    first = await sweeper.sweep(now=future, limit=1, max_batches=2)
    second = await sweeper.sweep(now=future, limit=1, max_batches=2)

    assert first.capped is True
    assert len(first.run_ids) == 2
    assert second.capped is False
    assert len(second.run_ids) == 1


async def test_dry_run_previews_only_first_batch() -> None:
    """dry-run 不写标记，循环会把同一批候选重复计数，所以只预览第一批。"""
    store = InMemoryRunStore()
    run_ids = [await _finished_run(store) for _ in range(3)]
    future = datetime.now(UTC) + timedelta(days=31)

    result = await _sweeper(store).sweep(now=future, limit=1, dry_run=True)

    assert result.batch == 1
    assert result.capped is True
    assert len(result.run_ids) == 1
    assert result.run_ids[0] in run_ids
    for run_id in run_ids:
        assert len(await store.events_after(run_id)) == 3


async def test_prunes_model_calls_by_created_at() -> None:
    store = InMemoryRunStore()
    calls = InMemoryModelCallStore()
    run_id = await _finished_run(store)
    rec = await store.get(run_id)
    assert rec is not None
    rec.token_in = 150  # 模拟 meter 已把计量累加到 runs
    now = datetime.now(UTC)
    await _call(calls, created_at=now - timedelta(days=200), token_in=100, run_id=run_id)
    await _call(calls, created_at=now - timedelta(days=10), token_in=50, run_id=run_id)

    result = await _sweeper(store, calls).sweep(now=now)

    assert result.calls == 1
    # 只删计量行：run 上的 token 汇总是历史账，不跟着改
    assert rec.token_in == 150
    remaining = calls.records
    assert len(remaining) == 1
    assert remaining[0].token_in == 50


async def test_sweep_cutoffs_follow_settings() -> None:
    store = InMemoryRunStore()
    calls = InMemoryModelCallStore()
    now = datetime.now(UTC)

    result = await _sweeper(store, calls).sweep(now=now)

    assert result.events_before == now - timedelta(days=30)
    assert result.calls_before == now - timedelta(days=90)
    assert result.content_before == now - timedelta(days=60)


async def test_invalid_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="limit"):
        await _sweeper(InMemoryRunStore()).sweep(limit=0)
    with pytest.raises(ValueError, match="max_batches"):
        await _sweeper(InMemoryRunStore()).sweep(max_batches=0)


# ---------------------------------------------------------------- 正文按时间清理（ADR-0023）


async def test_prunes_expired_run_content() -> None:
    """终态 run 过了正文保留期：正文清空、留标记，摘要与计量一概不动。"""
    store = InMemoryRunStore()
    run_id = await _finished_run(store)
    settings = _settings(event_retention_days=30, run_content_retention_days=30)

    result = await _sweeper(store, settings=settings).sweep(
        now=datetime.now(UTC) + timedelta(days=31)
    )

    assert result.content_run_ids == [run_id]
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.input == ""
    assert rec.output is None
    assert rec.content_pruned_at is not None
    # 摘要仍在：状态、失败归因、事件清理标记、计量都不受正文清理影响
    assert rec.status == RunStatus.COMPLETED.value
    assert rec.events_pruned_at is not None
    # 同一轮里事件先清、正文后清：正文不会比事件活得更久（ADR-0023 的顺序保证）
    assert rec.events_pruned_at <= rec.content_pruned_at
    assert rec.token_in == 0


async def test_content_can_outlive_events() -> None:
    """正文保留期长于事件时：回放先不可用，回答还留着（配置层强制正文 >= 事件）。"""
    store = InMemoryRunStore()
    run_id = await _finished_run(store)
    sweeper = _sweeper(store)  # 事件 30 天 / 正文 60 天

    first = await sweeper.sweep(now=datetime.now(UTC) + timedelta(days=31))

    rec = await store.get(run_id)
    assert rec is not None
    assert first.run_ids == [run_id]
    assert rec.events_pruned_at is not None
    assert first.content_run_ids == []
    assert rec.output == "重启打印服务"

    second = await sweeper.sweep(now=datetime.now(UTC) + timedelta(days=61))

    rec = await store.get(run_id)
    assert rec is not None
    assert second.content_run_ids == [run_id]
    assert rec.input == "" and rec.output is None


async def test_prunes_failed_run_without_answer() -> None:
    """失败的 run 没有回答，只有问题：正文清理照样要清掉 input（候选条件不是只看 output）。"""
    store = InMemoryRunStore()
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_701", session_id="sess_ret", message="帮我开单")
    await store.append(run_id, EventType.RUN_STARTED, {})
    await store.append(run_id, EventType.RUN_FAILED, {"error_code": "TOOL_ERROR"})
    rec = await store.get(run_id)
    assert rec is not None and rec.output is None

    result = await _sweeper(store).sweep(now=datetime.now(UTC) + timedelta(days=61))

    assert result.content_run_ids == [run_id]
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.input == ""
    assert rec.failure_category == "tool"


async def test_content_dry_run_previews_without_clearing() -> None:
    store = InMemoryRunStore()
    run_id = await _finished_run(store)

    result = await _sweeper(store).sweep(now=datetime.now(UTC) + timedelta(days=61), dry_run=True)

    assert result.content_run_ids == [run_id]
    rec = await store.get(run_id)
    assert rec is not None
    assert rec.output == "重启打印服务"
    assert rec.content_pruned_at is None


async def test_non_terminal_runs_keep_content() -> None:
    """等待审批的 run 可能挂很久，正文不能因为「够旧」被清掉。"""
    store = InMemoryRunStore()
    running_id = await _running_run(store)

    result = await _sweeper(store).sweep(now=datetime.now(UTC) + timedelta(days=365))

    assert result.content_run_ids == []
    rec = await store.get(running_id)
    assert rec is not None
    assert rec.input == "长任务"
    assert rec.content_pruned_at is None


async def test_pruned_content_is_gone_from_multi_turn_history() -> None:
    """多轮历史只认 output 非空：正文清空后那一轮自然消失，不需要额外过滤。"""
    store = InMemoryRunStore()
    await _finished_run(store, session_id="sess_content")
    assert len(await store.recent_turns(user_id="u_701", session_id="sess_content")) == 1

    await _sweeper(store).sweep(now=datetime.now(UTC) + timedelta(days=61))

    assert await store.recent_turns(user_id="u_701", session_id="sess_content") == []


async def test_content_prune_is_idempotent() -> None:
    store = InMemoryRunStore()
    run_id = await _finished_run(store)
    sweeper = _sweeper(store)
    future = datetime.now(UTC) + timedelta(days=61)

    first = await sweeper.sweep(now=future)
    second = await sweeper.sweep(now=future)

    assert first.content_run_ids == [run_id]
    # 标记写入后不再入选；空正文的 run 也不算候选
    assert second.content_run_ids == []


async def test_content_only_backlog_keeps_sweeping() -> None:
    """事件都清完、只剩正文积压时单轮仍要继续取批：收手条件必须包含正文。"""
    store = InMemoryRunStore()
    run_ids = {await _finished_run(store) for _ in range(3)}
    now = datetime.now(UTC)

    # 第一轮只清事件（正文保留 1000 天），制造「只有正文积压」的局面
    await _sweeper(store, settings=_settings(run_content_retention_days=1000)).sweep(
        now=now + timedelta(days=31)
    )

    result = await _sweeper(store).sweep(now=now + timedelta(days=61), limit=1)

    assert set(result.content_run_ids) == run_ids
    assert result.capped is False
