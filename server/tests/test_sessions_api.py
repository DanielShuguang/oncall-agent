"""会话列表与按会话取历史（ADR-0030）。"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore


async def _run(
    store: InMemoryRunStore,
    session_id: str,
    message: str,
    *,
    user_id: str = "u_102",
) -> str:
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        message=message,
    )
    return run_id


async def test_sessions_aggregate_runs_by_session(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_a", "打印机离线")
    await _run(mem_store, "sess_a", "还是不行")
    await _run(mem_store, "sess_b", "第二个会话")

    res = await client.get("/api/sessions")
    assert res.status_code == 200
    body = res.json()
    assert body["next_cursor"] is None
    items = body["items"]
    assert items[0]["session_id"] == "sess_b"
    a = next(item for item in items if item["session_id"] == "sess_a")
    assert a["title"] == "打印机离线"
    assert a["run_count"] == 2
    assert a["started_at"] is not None
    assert a["updated_at"] is not None


async def test_sessions_only_own_and_respects_limit(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_mine", "我的问题")
    await _run(mem_store, "sess_other", "别人的问题", user_id="u_205")

    res = await client.get("/api/sessions", params={"limit": 10})
    assert res.status_code == 200
    assert {item["session_id"] for item in res.json()["items"]} == {"sess_mine"}

    limited = await client.get("/api/sessions", params={"limit": 1})
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1


async def test_sessions_title_falls_back_and_truncates(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_blank", "   ")
    await _run(mem_store, "sess_blank", "真实问题")
    await _run(mem_store, "sess_none", "   ")
    await _run(mem_store, "sess_long", "打" * 100)
    await _run(mem_store, "sess_exact", "字" * 60)

    response = await client.get("/api/sessions")
    items = {item["session_id"]: item for item in response.json()["items"]}
    assert items["sess_blank"]["title"] == "真实问题"
    assert items["sess_none"]["title"] is None
    assert items["sess_long"]["title"] is not None
    assert len(items["sess_long"]["title"]) == 60
    assert items["sess_long"]["title"].endswith("…")
    assert items["sess_exact"]["title"] == "字" * 60


async def test_runs_can_be_filtered_by_session(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    a_run = await _run(mem_store, "sess_a", "会话 A")
    await _run(mem_store, "sess_b", "会话 B")

    res = await client.get("/api/runs", params={"session_id": "sess_a"})
    assert res.status_code == 200
    assert [item["run_id"] for item in res.json()["items"]] == [a_run]

    missing = await client.get("/api/runs", params={"session_id": "sess_missing"})
    assert missing.status_code == 200
    assert missing.json()["items"] == []


async def test_sessions_paginate_with_cursor(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_a", "会话 A")
    await asyncio.sleep(0.005)
    await _run(mem_store, "sess_b", "会话 B")
    await asyncio.sleep(0.005)
    await _run(mem_store, "sess_c", "会话 C")

    first = await client.get("/api/sessions", params={"limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert [item["session_id"] for item in first_body["items"]] == ["sess_c", "sess_b"]
    assert first_body["next_cursor"] is not None

    second = await client.get(
        "/api/sessions", params={"limit": 2, "cursor": first_body["next_cursor"]}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["session_id"] for item in second_body["items"]] == ["sess_a"]
    assert second_body["next_cursor"] is None


async def test_sessions_reject_invalid_cursor(client: AsyncClient) -> None:
    res = await client.get("/api/sessions", params={"cursor": "not-a-cursor"})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_session_history_pages_older_runs(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_a", "第一轮")
    await asyncio.sleep(0.005)
    second = await _run(mem_store, "sess_a", "第二轮")
    await asyncio.sleep(0.005)
    third = await _run(mem_store, "sess_a", "第三轮")

    first = await client.get("/api/runs", params={"session_id": "sess_a", "limit": 2})
    first_body = first.json()
    assert [item["run_id"] for item in first_body["items"]] == [third, second]
    assert first_body["next_cursor"] is not None

    older = await client.get(
        "/api/runs",
        params={"session_id": "sess_a", "limit": 2, "cursor": first_body["next_cursor"]},
    )
    older_body = older.json()
    assert len(older_body["items"]) == 1
    assert older_body["items"][0]["run_id"] not in {second, third}
    assert older_body["next_cursor"] is None


async def test_sessions_reject_bad_limit(client: AsyncClient) -> None:
    assert (await client.get("/api/sessions", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/sessions", params={"limit": 51})).status_code == 422


async def test_sessions_database_failure_is_503(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    mem_store.list_sessions = AsyncMock(side_effect=SQLAlchemyError("boom"))  # type: ignore[method-assign]

    res = await client.get("/api/sessions")
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"
