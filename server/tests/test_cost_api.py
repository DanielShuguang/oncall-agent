"""成本聚合接口（W4 D19）：口径、分组、日期边界、权限。"""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient

from app.gateway.meter import InMemoryModelCallStore, ModelCallRecord
from tests.support import auth_headers

ADMIN = auth_headers(roles=("admin",))


async def _record(
    store: InMemoryModelCallStore,
    *,
    run_id: str,
    model: str,
    user_id: str,
    created_at: datetime,
    token_in: int = 100,
    token_out: int = 20,
    cost_cents: int = 1,
) -> None:
    await store.record(
        ModelCallRecord(
            run_id=run_id,
            step="plan",
            provider="cloud" if model != "qwen" else "local",
            model=model,
            token_in=token_in,
            token_out=token_out,
            cost_cents=cost_cents,
            latency_ms=10,
            first_token_ms=None,
            status="ok",
            error=None,
            user_id=user_id,
            created_at=created_at,
        )
    )


async def test_cost_summary_groups_by_model(
    client: AsyncClient, mem_model_calls: InMemoryModelCallStore
) -> None:
    await _record(
        mem_model_calls,
        run_id="r1",
        model="gpt-test",
        user_id="u_102",
        created_at=datetime(2026, 11, 9, 10, tzinfo=UTC),
        cost_cents=3,
    )
    await _record(
        mem_model_calls,
        run_id="r2",
        model="gpt-test",
        user_id="u_205",
        created_at=datetime(2026, 11, 9, 11, tzinfo=UTC),
        cost_cents=4,
    )
    await _record(
        mem_model_calls,
        run_id="r3",
        model="qwen",
        user_id="u_102",
        created_at=datetime(2026, 11, 9, 12, tzinfo=UTC),
        cost_cents=0,
    )

    res = await client.get(
        "/api/admin/cost/summary",
        params={"from": "2026-11-09", "to": "2026-11-09", "group_by": "model"},
        headers=ADMIN,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_cents"] == 7
    assert body["calls"] == 3
    assert body["items"][0] == {
        "key": "gpt-test",
        "calls": 2,
        "token_in": 200,
        "token_out": 40,
        "cost_cents": 7,
    }


async def test_cost_summary_groups_by_day_and_user(
    client: AsyncClient, mem_model_calls: InMemoryModelCallStore
) -> None:
    await _record(
        mem_model_calls,
        run_id="r1",
        model="m",
        user_id="u_102",
        created_at=datetime(2026, 11, 8, 10, tzinfo=UTC),
    )
    await _record(
        mem_model_calls,
        run_id="r2",
        model="m",
        user_id="u_205",
        created_at=datetime(2026, 11, 9, 10, tzinfo=UTC),
    )

    by_day = await client.get(
        "/api/admin/cost/summary",
        params={"from": "2026-11-08", "to": "2026-11-09", "group_by": "day"},
        headers=ADMIN,
    )
    assert [item["key"] for item in by_day.json()["items"]] == ["2026-11-08", "2026-11-09"]

    by_user = await client.get(
        "/api/admin/cost/summary",
        params={"from": "2026-11-08", "to": "2026-11-09", "group_by": "user"},
        headers=ADMIN,
    )
    assert {item["key"] for item in by_user.json()["items"]} == {"u_102", "u_205"}


async def test_cost_summary_end_date_is_inclusive(
    client: AsyncClient, mem_model_calls: InMemoryModelCallStore
) -> None:
    await _record(
        mem_model_calls,
        run_id="r1",
        model="m",
        user_id="u_102",
        created_at=datetime(2026, 11, 9, 23, 59, 59, tzinfo=UTC),
    )
    await _record(
        mem_model_calls,
        run_id="r2",
        model="m",
        user_id="u_102",
        created_at=datetime(2026, 11, 10, 0, 0, tzinfo=UTC),
    )

    res = await client.get(
        "/api/admin/cost/summary",
        params={"from": "2026-11-09", "to": "2026-11-09"},
        headers=ADMIN,
    )
    assert res.json()["calls"] == 1


async def test_cost_summary_requires_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/cost/summary")
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_cost_summary_rejects_invalid_range(client: AsyncClient) -> None:
    res = await client.get(
        "/api/admin/cost/summary",
        params={"from": "2026-11-10", "to": "2026-11-09"},
        headers=ADMIN,
    )
    assert res.status_code == 422
    assert res.json()["code"] == "INVALID_RANGE"


async def test_cost_summary_rejects_bad_group_by(client: AsyncClient) -> None:
    res = await client.get(
        "/api/admin/cost/summary",
        params={"group_by": "week"},
        headers=ADMIN,
    )
    assert res.status_code == 422
