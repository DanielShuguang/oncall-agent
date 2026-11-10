"""运行查询与断线续传接口。"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from app.core.store import InMemoryRunStore
from app.gateway.meter import InMemoryModelCallStore, ModelCallRecord
from app.main import app
from app.schemas.event import EventType, RunStatus
from tests.support import auth_headers


async def _seed_run(
    store: InMemoryRunStore,
    *,
    client_msg_id: str | None = None,
    user_id: str = "u_102",
    status: str = "completed",
) -> str:
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id=user_id,
        session_id="sess_1",
        message="打印机离线",
        client_msg_id=client_msg_id or f"cmsg_{uuid.uuid4().hex[:8]}",
    )
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock", "max_steps": 12})
    await store.append(run_id, EventType.STEP_STARTED, {"node": "intake"})
    await store.append(run_id, EventType.STEP_COMPLETED, {"node": "intake"})
    await store.append(run_id, EventType.MESSAGE_COMPLETED, {"text": "重启打印服务"})
    if status == "failed":
        await store.append(
            run_id,
            EventType.RUN_FAILED,
            {"error_code": "TOOL_ERROR", "message": "失败", "at_step": 4},
        )
    else:
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
    assert body["events_pruned_at"] is None


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


async def test_list_runs_paginates_with_cursor(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_ids = [await _seed_run(mem_store) for _ in range(3)]
    base = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    for index, run_id in enumerate(run_ids):
        record = await mem_store.get(run_id)
        assert record is not None
        record.started_at = base + timedelta(minutes=index)

    first = await client.get("/api/runs", params={"limit": 2})
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]

    second = await client.get("/api/runs", params={"limit": 2, "cursor": body["next_cursor"]})
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None
    assert second_body["items"][0]["run_id"] == run_ids[0]


async def test_list_runs_filters_status_and_owner(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    failed_id = await _seed_run(mem_store, status="failed")
    await _seed_run(mem_store)
    await _seed_run(mem_store, user_id="u_205")

    res = await client.get("/api/runs", params={"status": "failed"})
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["run_id"] for item in items] == [failed_id]
    assert items[0]["failure_category"] == "tool"
    assert items[0]["error_code"] == "TOOL_ERROR"


async def test_list_runs_rejects_invalid_cursor(client: AsyncClient) -> None:
    res = await client.get("/api/runs", params={"cursor": "not-base64"})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_list_runs_rejects_cursor_with_non_uuid_run_id(client: AsyncClient) -> None:
    cursor = base64.urlsafe_b64encode(b"2026-11-09T10:00:00+00:00|not-a-uuid").decode()
    res = await client.get("/api/runs", params={"cursor": cursor})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_list_runs_rejects_naive_cursor_datetime(client: AsyncClient) -> None:
    cursor = base64.urlsafe_b64encode(f"2026-11-09T10:00:00|{uuid.uuid4()}".encode()).decode()
    res = await client.get("/api/runs", params={"cursor": cursor})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_run_detail_includes_model_calls(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    mem_model_calls: InMemoryModelCallStore,
) -> None:
    run_id = await _seed_run(mem_store)
    await mem_model_calls.record(
        ModelCallRecord(
            run_id=run_id,
            step="plan",
            provider="local",
            model="qwen-test",
            token_in=100,
            token_out=20,
            cost_cents=0,
            latency_ms=12,
            first_token_ms=None,
            status="ok",
            error=None,
            user_id="u_102",
        )
    )

    res = await client.get(f"/api/runs/{run_id}")
    assert res.status_code == 200
    calls = res.json()["model_calls"]
    assert len(calls) == 1
    assert calls[0]["step"] == "plan"
    assert calls[0]["token_in"] == 100


async def test_pruned_events_are_marked_in_detail(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    """保留清理后 run 仍在：详情带 events_pruned_at，事件接口返回空而不是 404。"""
    run_id = await _seed_run(mem_store)
    pruned = await mem_store.prune_events(finished_before=datetime.now(UTC) + timedelta(days=365))
    assert pruned.run_ids == [run_id]

    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["events_pruned_at"] is not None
    assert detail["event_count"] == 0
    # 摘要与回答保留：回放不可用不等于 run 消失
    assert detail["output"] == "重启打印服务"
    assert detail["status"] == RunStatus.COMPLETED.value

    events = await client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    payload = events.json()
    assert payload["events"] == []
    assert payload["run_status"] == RunStatus.COMPLETED.value

    # 列表与详情共用同一个 summary，标记也要出现在列表里
    listing = (await client.get("/api/runs")).json()
    assert listing["items"][0]["events_pruned_at"] is not None
