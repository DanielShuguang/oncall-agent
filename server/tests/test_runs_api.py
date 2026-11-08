"""运行查询与断线续传接口。"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.core.store import InMemoryRunStore
from app.main import app
from app.schemas.event import EventType, RunStatus
from tests.support import auth_headers


async def _seed_run(store: InMemoryRunStore) -> str:
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id="u_102",
        session_id="sess_1",
        message="打印机离线",
        client_msg_id="cmsg_seed",
    )
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock", "max_steps": 12})
    await store.append(run_id, EventType.STEP_STARTED, {"node": "intake"})
    await store.append(run_id, EventType.STEP_COMPLETED, {"node": "intake"})
    await store.append(run_id, EventType.MESSAGE_COMPLETED, {"text": "重启打印服务"})
    await store.append(
        run_id,
        EventType.RUN_COMPLETED,
        {"status": "completed", "steps": 1, "token_in": 12, "token_out": 3, "cost_cents": 1},
    )
    return run_id


async def test_get_run_detail(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(f"/api/runs/{run_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == run_id
    assert body["status"] == RunStatus.COMPLETED.value
    assert body["input"] == "打印机离线"
    assert body["output"] == "重启打印服务"
    assert body["event_count"] == 5
    assert body["token_in"] == 12
    assert body["cost_cents"] == 1
    assert body["finished_at"] is not None


async def test_get_run_unknown_returns_404(client: AsyncClient) -> None:
    res = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert res.status_code == 404


async def test_events_after_seq(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(f"/api/runs/{run_id}/events", params={"after_seq": 2})
    assert res.status_code == 200
    body = res.json()
    assert [e["seq"] for e in body["events"]] == [3, 4, 5]
    assert body["next_seq"] == 5
    assert body["run_status"] == RunStatus.COMPLETED.value


async def test_events_last_event_id_header(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": "3"},
    )
    assert res.status_code == 200
    assert [e["seq"] for e in res.json()["events"]] == [4, 5]


async def test_explicit_after_seq_overrides_header(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(
        f"/api/runs/{run_id}/events",
        params={"after_seq": 0},
        headers={"Last-Event-ID": "3"},
    )
    assert [e["seq"] for e in res.json()["events"]] == [1, 2, 3, 4, 5]


async def test_invalid_last_event_id_falls_back_to_zero(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": "not-a-number"},
    )
    assert [e["seq"] for e in res.json()["events"]] == [1, 2, 3, 4, 5]


async def test_events_limit_and_next_seq(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(f"/api/runs/{run_id}/events", params={"limit": 2})
    body = res.json()
    assert [e["seq"] for e in body["events"]] == [1, 2]
    assert body["next_seq"] == 2


async def test_events_unknown_run_returns_404(client: AsyncClient) -> None:
    res = await client.get(f"/api/runs/{uuid.uuid4()}/events")
    assert res.status_code == 404


async def test_run_of_another_user_is_404(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    """不能读别人的 run，也不能用 403 暴露"它存在"。"""
    run_id = await _seed_run(mem_store)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=auth_headers("u_205"),
    ) as other:
        assert (await other.get(f"/api/runs/{run_id}")).status_code == 404
        assert (await other.get(f"/api/runs/{run_id}/events")).status_code == 404
