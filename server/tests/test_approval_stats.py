"""审批积压与等待统计（ADR-0048）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.approvals.store import InMemoryApprovalStore
from app.approvals.types import ApprovalRecord, ApprovalStats
from tests.support import auth_headers

EMPLOYEE = auth_headers("u_102", ("employee",))
APPROVER = auth_headers("u_900", ("approver",))

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _record(
    approval_id: str,
    *,
    status: str = "pending",
    created_at: datetime = NOW,
    resolved_at: datetime | None = None,
    requested_by: str = "u_102",
) -> ApprovalRecord:
    return ApprovalRecord(
        id=approval_id,
        run_id=str(uuid.uuid4()),
        call_id="call_1",
        tool_name="create_ticket",
        args={},
        risk_level="medium",
        status=status,
        requested_by=requested_by,
        expires_at=created_at + timedelta(minutes=10),
        created_at=created_at,
        resolved_at=resolved_at,
        resolved_by="u_900" if resolved_at is not None else None,
    )


async def test_inmemory_stats_counts_pending_and_windowed_decisions() -> None:
    store = InMemoryApprovalStore()
    await store.create(_record("p1", created_at=NOW - timedelta(seconds=90)))
    await store.create(_record("p2", created_at=NOW - timedelta(seconds=30)))
    # 已过期但尚未被 expire_due 收敛的 pending 不算积压
    await store.create(_record("stale", created_at=NOW - timedelta(hours=1)))
    await store.create(
        _record(
            "a1",
            status="approved",
            created_at=NOW - timedelta(hours=2),
            resolved_at=NOW - timedelta(hours=1),
        )
    )
    await store.create(
        _record(
            "r1",
            status="rejected",
            created_at=NOW - timedelta(hours=3),
            resolved_at=NOW - timedelta(minutes=150),
        )
    )
    # expired 不算人工等待；窗口外的决议也不进统计
    await store.create(
        _record(
            "e1",
            status="expired",
            created_at=NOW - timedelta(hours=4),
            resolved_at=NOW - timedelta(hours=3),
        )
    )
    await store.create(
        _record(
            "old",
            status="approved",
            created_at=NOW - timedelta(days=10),
            resolved_at=NOW - timedelta(days=9),
        )
    )

    stats = await store.stats(since=NOW - timedelta(days=7), now=NOW)

    assert stats.pending_count == 2
    assert stats.oldest_pending_age_s == 90
    assert stats.decided_count == 2
    assert stats.avg_wait_ms == 2_700_000
    assert stats.max_wait_ms == 3_600_000


async def test_inmemory_stats_empty_returns_nulls() -> None:
    stats = await InMemoryApprovalStore().stats(since=NOW - timedelta(days=7), now=NOW)
    assert stats == ApprovalStats(0, None, 0, None, None)


async def test_approval_stats_requires_approver(client: AsyncClient) -> None:
    res = await client.get("/api/approvals/stats", headers=EMPLOYEE)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_approval_stats_returns_aggregates(
    client: AsyncClient, mem_approvals: InMemoryApprovalStore
) -> None:
    now = datetime.now(UTC)
    await mem_approvals.create(_record("p1", created_at=now - timedelta(seconds=120)))
    await mem_approvals.create(
        _record(
            "a1",
            status="approved",
            created_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
        )
    )

    res = await client.get("/api/approvals/stats?days=7", headers=APPROVER)

    assert res.status_code == 200
    body = res.json()
    assert body["days"] == 7
    assert body["pending_count"] == 1
    assert body["oldest_pending_age_s"] >= 120
    assert body["decided_count"] == 1
    assert body["avg_wait_ms"] == 3_600_000
    assert body["max_wait_ms"] == 3_600_000


async def test_approval_stats_validates_days(client: AsyncClient) -> None:
    for days in (0, 91):
        res = await client.get(f"/api/approvals/stats?days={days}", headers=APPROVER)
        assert res.status_code == 422


async def test_approval_stats_database_failure_is_503(
    client: AsyncClient,
    mem_approvals: InMemoryApprovalStore,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        mem_approvals,
        "stats",
        AsyncMock(side_effect=SQLAlchemyError("boom")),
    )

    res = await client.get("/api/approvals/stats", headers=APPROVER)

    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"
