"""预算账本快照与今日用量接口（ADR-0028）。

覆盖三件事：快照能看到未结算预扣、stale 只按已知年龄统计、
`GET /admin/budgets/usage` 在账本故障时显式 503 而不是显示「没花钱」。
Redis 用例需要 `ONCALL_TEST_REDIS_URL`，没有就跳过。
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from app.budgets.observability import summarize
from app.core.limits import (
    RESERVATION_STALE_S,
    InMemoryBudgetLedger,
    InMemoryUserBudgetLedger,
    LedgerSnapshot,
    LedgerUnavailable,
    RedisUserBudgetLedger,
    ReservationSnapshot,
    budget_day,
    get_budget_ledger,
    get_user_budget_ledger,
    set_budget_ledger,
    set_user_budget_ledger,
)
from tests.support import auth_headers

ADMIN = auth_headers("admin_1", ("admin",))


# --------------------------------------------------------------------------- #
# 快照
# --------------------------------------------------------------------------- #


async def test_global_snapshot_tracks_reservations_and_settlement() -> None:
    ledger = InMemoryBudgetLedger(limit_cents=100)
    first = await ledger.reserve(30)
    second = await ledger.reserve(20)
    assert first is not None and second is not None

    snapshot = await ledger.snapshot()
    assert snapshot.spent_cents == 50
    assert len(snapshot.reservations) == 2
    assert {item.token for item in snapshot.reservations} == {first.token, second.token}
    assert all(item.age_s is not None and item.age_s >= 0 for item in snapshot.reservations)

    # 实际只花 7 分：回冲 30，加回 7，剩下一笔 20 分预扣仍在账上
    await ledger.settle(first, 7)
    snapshot = await ledger.snapshot()
    assert snapshot.spent_cents == 27
    assert [item.token for item in snapshot.reservations] == [second.token]
    assert snapshot.reservations[0].cents == 20


async def test_user_snapshot_groups_by_user_and_clears_on_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import limits as limits_module

    monkeypatch.setattr(limits_module, "_utc_day", lambda: "2026-11-11")
    ledger = InMemoryUserBudgetLedger()
    first = await ledger.reserve("u_1", 5, limit_cents=10)
    second = await ledger.reserve("u_2", 3, limit_cents=10)
    assert first is not None and second is not None
    await ledger.settle(second, 2)

    snapshot = await ledger.snapshot()
    assert set(snapshot) == {"u_1", "u_2"}
    assert snapshot["u_1"].spent_cents == 5
    assert snapshot["u_1"].reservations[0].token == first.token
    assert snapshot["u_2"].spent_cents == 2
    assert snapshot["u_2"].reservations == ()

    monkeypatch.setattr(limits_module, "_utc_day", lambda: "2026-11-12")
    assert await ledger.snapshot() == {}


def test_summarize_counts_stale_only_when_age_is_known() -> None:
    snapshot = LedgerSnapshot(
        spent_cents=70,
        reservations=(
            ReservationSnapshot(token="a", cents=10, age_s=1.0),
            ReservationSnapshot(token="b", cents=20, age_s=301.0),
            ReservationSnapshot(token="c", cents=5, age_s=None),
        ),
    )
    stats = summarize(snapshot, stale_after_s=RESERVATION_STALE_S)
    assert stats.reserved_cents == 35
    assert stats.reservation_count == 3
    assert stats.stale_count == 1
    assert stats.stale_cents == 20
    # 没有时间戳的旧格式不参与「最老」统计，避免报表显示一个假的年龄
    assert stats.oldest_age_s == 301.0


# --------------------------------------------------------------------------- #
# 管理接口
# --------------------------------------------------------------------------- #


async def test_budget_usage_requires_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/budgets/usage", headers=auth_headers())
    assert res.status_code == 403


async def test_budget_usage_returns_global_and_user_stats(client: AsyncClient) -> None:
    assert await get_budget_ledger().reserve(12) is not None
    assert await get_user_budget_ledger().reserve("u_1", 5, limit_cents=10) is not None

    res = await client.get("/api/admin/budgets/usage", headers=ADMIN)
    assert res.status_code == 200
    body = res.json()
    assert body["day"] == budget_day()
    assert body["stale_after_s"] == RESERVATION_STALE_S
    assert body["global_usage"]["spent_cents"] == 12
    assert body["global_usage"]["reservation_count"] == 1
    assert body["users"] == [
        {
            "user_id": "u_1",
            "spent_cents": 5,
            "reserved_cents": 5,
            "reservation_count": 1,
            "stale_count": 0,
            "stale_cents": 0,
            "oldest_age_s": 0.0,
        }
    ]


class _BrokenGlobalLedger(InMemoryBudgetLedger):
    async def snapshot(self) -> LedgerSnapshot:
        raise LedgerUnavailable("redis down")


class _BrokenUserLedger(InMemoryUserBudgetLedger):
    async def snapshot(self) -> dict[str, LedgerSnapshot]:
        raise LedgerUnavailable("redis down")


@pytest.mark.parametrize("which", ["global", "user"])
async def test_budget_usage_503_when_ledger_unavailable(client: AsyncClient, which: str) -> None:
    if which == "global":
        set_budget_ledger(_BrokenGlobalLedger(limit_cents=100))
    else:
        set_user_budget_ledger(_BrokenUserLedger())

    res = await client.get("/api/admin/budgets/usage", headers=ADMIN)
    assert res.status_code == 503
    assert res.json()["code"] == "LEDGER_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Redis：真实快照读取（无 Redis 时跳过）
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.environ.get("ONCALL_TEST_REDIS_URL"),
    reason="需要 ONCALL_TEST_REDIS_URL 指向一个可清空的测试 redis",
)
async def test_redis_user_ledger_snapshot_roundtrip() -> None:
    ledger = RedisUserBudgetLedger(os.environ["ONCALL_TEST_REDIS_URL"])
    user = f"test_{uuid.uuid4().hex[:10]}"
    try:
        reservation = await ledger.reserve(user, 5, limit_cents=8)
        assert reservation is not None
        snapshot = await ledger.snapshot()
        assert snapshot[user].spent_cents == 5
        assert snapshot[user].reservations[0].token == reservation.token
        assert snapshot[user].reservations[0].age_s is not None

        await ledger.settle(reservation, 2)
        snapshot = await ledger.snapshot()
        # 用户集合保留到当天结束：结算后仍能看到这个人今天花了 2 分
        assert snapshot[user].spent_cents == 2
        assert snapshot[user].reservations == ()
    finally:
        client = ledger._redis()
        await client.delete(
            ledger._key(user),
            ledger._reservations_key(user),
            ledger._users_key(),
        )
        await ledger.close()
