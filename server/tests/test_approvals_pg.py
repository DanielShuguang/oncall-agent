"""Postgres 审批存储集成测试（默认跳过）。

验证真实库上的三条约束：
- 部分唯一索引：同一 run 同一工具只有一条 pending
- 原子迁移：并发 resolve 只有一方执行写工具
- 超时回收：expired 同时把 run 推到 failed(APPROVAL_TIMEOUT)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.approvals.service import ApprovalService
from app.approvals.store import PostgresApprovalStore
from app.core.store import PostgresRunStore
from app.core.store import append_event_in_session as real_append_event_in_session
from app.models import Approval, ApprovalGrant, Base
from app.schemas.event import EventType
from app.tools.registry import Identity
from app.tools.tickets import InMemoryTicketRepository

APPROVER_A = Identity(user_id="u_900", roles=frozenset({"approver"}))
APPROVER_B = Identity(user_id="u_901", roles=frozenset({"approver"}))


@pytest_asyncio.fixture
async def pg_approvals() -> AsyncIterator[
    tuple[
        PostgresRunStore, PostgresApprovalStore, ApprovalService, async_sessionmaker[AsyncSession]
    ]
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
    runs = PostgresRunStore(sessionmaker)
    approvals = PostgresApprovalStore(sessionmaker)
    service = ApprovalService(runs, approvals)
    try:
        yield runs, approvals, service, sessionmaker
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _new_run(runs: PostgresRunStore) -> str:
    run_id = str(uuid.uuid4())
    await runs.create(
        run_id=run_id,
        user_id="u_102",
        session_id="sess_pg",
        message="打印机坏了，帮我开一张报修工单",
    )
    return run_id


async def _request(runs: PostgresRunStore, service: ApprovalService, run_id: str) -> str:
    info = await service.request(
        run_id=run_id,
        call_id="call_1",
        session_id="sess_pg",
        tool_name="create_ticket",
        args={"title": "打印机离线", "category": "hardware", "priority": "P2"},
        risk_level="medium",
        state={
            "run_id": run_id,
            "user": {"id": "u_102", "roles": ["employee"], "session_id": "sess_pg"},
            "query": "打印机坏了，帮我开一张报修工单",
            "intent": "ticket_create",
            "incident_type": "hardware",
            "retrieved": [],
            "citations": [],
            "plan": [],
            "tool_results": [],
            "step": 5,
            "verify_ok": True,
            "replan_count": 0,
            "failed_tools": [],
        },
        requested_by="u_102",
    )
    # 真实链路里 chat 层会落库 approval.required；这里显式补上，
    # 否则 run 还是 running，resolve 会被 APPROVAL_NOT_READY 拒绝
    await runs.append(run_id, EventType.APPROVAL_REQUIRED, {"approval_id": info.approval_id})
    return info.approval_id


async def test_pg_event_failure_rolls_back_decision(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """决议与事件同一事务：事件写失败时审批必须仍是 pending。

    否则会留下「已通过、没有 approval.resolved、run 停在 awaiting_approval」
    的半截状态，客户端永远等不到终态（ADR-0016）。
    """
    runs, approvals, service, _ = pg_approvals
    run_id = await _new_run(runs)
    approval_id = await _request(runs, service, run_id)

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("event write failed")

    monkeypatch.setattr("app.approvals.service.append_event_in_session", boom)

    with pytest.raises(RuntimeError):
        await service.resolve(approval_id, APPROVER_A, decision="approved", scope="session")

    record = await approvals.get(approval_id)
    assert record is not None and record.status == "pending"
    assert (await runs.status(run_id)) == "awaiting_approval"
    types = [event.type.value for event in await runs.events_after(run_id)]
    assert "approval.resolved" not in types
    # 同一事务里的 session 授权也必须回滚
    assert not await approvals.is_granted(
        user_id="u_102",
        session_id="sess_pg",
        tool_name="create_ticket",
        at=datetime.now(UTC) + timedelta(hours=1),
    )


async def test_pg_second_event_failure_rolls_back_decision(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """拒绝要写 approval.resolved + run.failed 两条事件；第二条失败也整体回滚。"""
    runs, approvals, service, _ = pg_approvals
    run_id = await _new_run(runs)
    approval_id = await _request(runs, service, run_id)

    calls = 0

    async def flaky(
        session: Any,
        run_id: str,
        event_type: Any,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second event failed")
        return await real_append_event_in_session(session, run_id, event_type, payload)

    monkeypatch.setattr("app.approvals.service.append_event_in_session", flaky)

    with pytest.raises(RuntimeError):
        await service.resolve(approval_id, APPROVER_A, decision="rejected")

    assert calls == 2, "拒绝应写 approval.resolved + run.failed，第二条失败才触发回滚"
    record = await approvals.get(approval_id)
    assert record is not None and record.status == "pending"
    assert (await runs.status(run_id)) == "awaiting_approval"
    types = [event.type.value for event in await runs.events_after(run_id)]
    assert "approval.resolved" not in types
    assert "run.failed" not in types


async def test_pg_approval_resume_executes_once(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
    mem_tickets: InMemoryTicketRepository,
) -> None:
    runs, approvals, service, _ = pg_approvals
    run_id = await _new_run(runs)
    approval_id = await _request(runs, service, run_id)

    assert (await approvals.get(approval_id)) is not None
    assert (await runs.status(run_id)) == "awaiting_approval"

    resolved = await service.resolve(approval_id, APPROVER_A, decision="approved")
    assert resolved.status == "approved"
    assert (await runs.status(run_id)) == "completed"
    assert mem_tickets.count() == 1

    events = await runs.events_after(run_id)
    types = [event.type.value for event in events]
    assert "approval.required" in types
    assert "approval.resolved" in types
    assert "run.completed" in types


async def test_pg_concurrent_resolve_executes_write_once(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
    mem_tickets: InMemoryTicketRepository,
) -> None:
    runs, _, service, _ = pg_approvals
    run_id = await _new_run(runs)
    approval_id = await _request(runs, service, run_id)

    await asyncio.gather(
        service.resolve(approval_id, APPROVER_A, decision="approved"),
        service.resolve(approval_id, APPROVER_B, decision="approved"),
    )
    # 原子迁移保证只有一方 changed=True，写工具只执行一次
    assert mem_tickets.count() == 1


async def test_pg_expired_approval_fails_run(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
    mem_tickets: InMemoryTicketRepository,
) -> None:
    runs, _, service, sessionmaker = pg_approvals
    run_id = await _new_run(runs)
    approval_id = await _request(runs, service, run_id)

    async with sessionmaker() as session, session.begin():
        row = await session.scalar(select(Approval).where(Approval.id == uuid.UUID(approval_id)))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    resolved = await service.resolve(approval_id, APPROVER_A, decision="approved")
    assert resolved.status == "expired"
    assert (await runs.status(run_id)) == "failed"
    assert mem_tickets.count() == 0
    rec = await runs.get(run_id)
    assert rec is not None and rec.error_code == "APPROVAL_TIMEOUT"


async def test_pg_session_grant_is_user_scoped(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
    mem_tickets: InMemoryTicketRepository,
) -> None:
    runs, approvals, service, _ = pg_approvals
    run_id = await _new_run(runs)
    approval_id = await _request(runs, service, run_id)

    await service.resolve(approval_id, APPROVER_A, decision="approved", scope="session")
    now = datetime.now(UTC)
    assert await approvals.is_granted(
        user_id="u_102", session_id="sess_pg", tool_name="create_ticket", at=now
    )
    assert not await approvals.is_granted(
        user_id="u_555", session_id="sess_pg", tool_name="create_ticket", at=now
    )
    assert mem_tickets.count() == 1


async def test_pg_prunes_resolved_snapshots_and_expired_grants(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
) -> None:
    """ADR-0027：只清已决议且早于阈值的快照；过期授权删行，未过期的照常生效。"""
    runs, approvals, _, sessionmaker = pg_approvals
    run_id = uuid.UUID(await _new_run(runs))
    now = datetime.now(UTC)
    snapshot = {"run_id": str(run_id), "node": "act", "query": "打印机坏了"}
    old_id = uuid.uuid4()
    pending_id = uuid.uuid4()
    async with sessionmaker() as session, session.begin():
        session.add_all(
            [
                Approval(
                    id=old_id,
                    run_id=run_id,
                    call_id="call_old",
                    tool_name="create_ticket",
                    args={"title": "打印机报修"},
                    risk_level="medium",
                    status="approved",
                    requested_by="u_102",
                    resolved_by="u_900",
                    reason="确认开单",
                    scope="once",
                    state=dict(snapshot),
                    expires_at=now - timedelta(days=90),
                    created_at=now - timedelta(days=90),
                    resolved_at=now - timedelta(days=90),
                ),
                Approval(
                    id=pending_id,
                    run_id=run_id,
                    call_id="call_pending",
                    tool_name="query_cmdb",
                    args={},
                    risk_level="low",
                    status="pending",
                    requested_by="u_102",
                    state=dict(snapshot),
                    expires_at=now + timedelta(minutes=30),
                    created_at=now - timedelta(days=90),
                ),
                ApprovalGrant(
                    user_id="u_102",
                    session_id="sess_dead",
                    tool_name="create_ticket",
                    granted_by="u_900",
                    expires_at=now - timedelta(days=1),
                ),
                ApprovalGrant(
                    user_id="u_102",
                    session_id="sess_live",
                    tool_name="create_ticket",
                    granted_by="u_900",
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )

    cutoff = now - timedelta(days=60)
    # dry-run 只计数
    assert await approvals.prune_snapshots(resolved_before=cutoff, dry_run=True) == 1
    kept = await approvals.get(str(old_id))
    assert kept is not None and kept.state == snapshot

    assert await approvals.prune_snapshots(resolved_before=cutoff) == 1
    cleared = await approvals.get(str(old_id))
    assert cleared is not None
    # 快照清空、决议证据保留；挂起行即使很老也不清（恢复执行还要读快照）
    assert cleared.state == {}
    assert cleared.args == {"title": "打印机报修"}
    assert cleared.reason == "确认开单"
    pending = await approvals.get(str(pending_id))
    assert pending is not None and pending.state == snapshot
    # 幂等：空对象不是快照，下一轮不再入选
    assert await approvals.prune_snapshots(resolved_before=cutoff) == 0

    assert await approvals.prune_grants(expired_before=now, dry_run=True) == 1
    assert await approvals.prune_grants(expired_before=now) == 1
    assert await approvals.is_granted(
        user_id="u_102", session_id="sess_live", tool_name="create_ticket", at=now
    )
    async with sessionmaker() as session:
        remaining = await session.scalar(
            select(func.count()).select_from(ApprovalGrant).where(ApprovalGrant.user_id == "u_102")
        )
    assert remaining == 1
    assert await approvals.prune_grants(expired_before=now) == 0


async def test_pg_stats_counts_pending_and_decided(
    pg_approvals: tuple[PostgresRunStore, PostgresApprovalStore, ApprovalService, Any],
) -> None:
    """真实 PG 上验证两条聚合：pending 积压与窗口内决议等待（ADR-0048）。"""
    runs, approvals, service, sessionmaker = pg_approvals
    approver = Identity(user_id="u_900", roles=frozenset({"approver"}))

    first_run = await _new_run(runs)
    first_id = await _request(runs, service, first_run)
    second_run = await _new_run(runs)
    second_id = await _request(runs, service, second_run)

    now = datetime.now(UTC)
    resolved, changed = await approvals.resolve(
        second_id,
        status="approved",
        resolved_by="u_900",
        reason=None,
        scope="once",
        at=now,
    )
    assert resolved is not None and changed

    stats = await service.stats(approver, days=7, now=now)

    assert stats.pending_count == 1
    assert stats.oldest_pending_age_s is not None and stats.oldest_pending_age_s >= 0
    assert stats.decided_count == 1
    assert stats.avg_wait_ms is not None and stats.avg_wait_ms >= 0
    assert stats.max_wait_ms == stats.avg_wait_ms
    assert len(stats.daily) == 1
    assert stats.daily[0].day == now.date()
    assert stats.daily[0].decided_count == 1
    assert stats.daily[0].avg_wait_ms == stats.avg_wait_ms

    by_tool = await service.stats(approver, days=7, now=now, group_by="tool")
    assert len(by_tool.groups) == 1
    assert by_tool.groups[0].key == "create_ticket"
    assert by_tool.groups[0].decided_count == 1
    assert by_tool.groups[0].avg_wait_ms == stats.avg_wait_ms
    assert by_tool.groups[0].max_wait_ms == stats.max_wait_ms
    assert by_tool.groups_truncated is False

    by_approver = await service.stats(approver, days=7, now=now, group_by="approver")
    assert len(by_approver.groups) == 1
    assert by_approver.groups[0].key == "u_900"

    # 已过期待办即使还没被 expire_due 收敛，也不计入积压
    async with sessionmaker() as session:
        await session.execute(
            update(Approval)
            .where(Approval.id == first_id)
            .values(expires_at=now - timedelta(seconds=1))
        )
        await session.commit()
    stale_stats = await approvals.stats(since=now - timedelta(days=7), now=now)
    assert stale_stats.pending_count == 0
    assert stale_stats.oldest_pending_age_s is None
