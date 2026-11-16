"""会话置顶审计的管理端读取（ADR-0081）。"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore
from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))


async def _pin_once(
    store: InMemoryRunStore, *, user_id: str, session_id: str, pin: bool = True
) -> None:
    await store.create(
        run_id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=session_id,
        message="打印机离线",
    )
    if pin:
        assert await store.pin_session(user_id=user_id, session_id=session_id) is True
    else:
        assert await store.unpin_session(user_id=user_id, session_id=session_id) is True


async def test_session_pin_audits_require_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/session-pins")
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_list_session_pin_audits(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    await _pin_once(mem_store, user_id="u_102", session_id="sess_a")
    await asyncio.sleep(0.002)
    await _pin_once(mem_store, user_id="u_103", session_id="sess_b")
    await asyncio.sleep(0.002)
    assert await mem_store.unpin_session(user_id="u_102", session_id="sess_a") is True

    res = await client.get("/api/admin/session-pins", headers=ADMIN)
    assert res.status_code == 200
    items = res.json()["items"]
    assert [(item["user_id"], item["session_id"], item["action"]) for item in items] == [
        ("u_102", "sess_a", "unpin"),
        ("u_103", "sess_b", "pin"),
        ("u_102", "sess_a", "pin"),
    ]
    assert items[0]["id"]
    assert items[0]["created_at"]

    filtered = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"user_id": "u_102", "action": "pin"},
    )
    assert filtered.status_code == 200
    assert [item["session_id"] for item in filtered.json()["items"]] == ["sess_a"]
    by_session = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"session_id": "sess_a"},
    )
    assert by_session.status_code == 200
    assert [item["action"] for item in by_session.json()["items"]] == ["unpin", "pin"]
    limited = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 1},
    )
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1


async def test_session_pin_audits_paginate(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _pin_once(mem_store, user_id="u_102", session_id="sess_a")
    await asyncio.sleep(0.002)
    await _pin_once(mem_store, user_id="u_103", session_id="sess_b")
    await asyncio.sleep(0.002)
    await _pin_once(mem_store, user_id="u_102", session_id="sess_c")

    first = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 2},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"]

    second = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None
    first_ids = {item["id"] for item in first_body["items"]}
    assert not first_ids & {item["id"] for item in second_body["items"]}

    bad = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"cursor": "not-a-cursor"},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_CURSOR"

    filtered = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"user_id": "u_102", "limit": 1},
    )
    assert filtered.status_code == 200
    filtered_cursor = filtered.json()["next_cursor"]
    assert filtered_cursor
    mismatch = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 1, "cursor": filtered_cursor},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "INVALID_CURSOR"
    action_mismatch = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"user_id": "u_102", "action": "pin", "limit": 1, "cursor": filtered_cursor},
    )
    assert action_mismatch.status_code == 400
    assert action_mismatch.json()["code"] == "INVALID_CURSOR"

    by_session = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"session_id": "sess_a", "limit": 1},
    )
    session_cursor = by_session.json()["next_cursor"]
    assert session_cursor
    session_mismatch = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"session_id": "sess_b", "limit": 1, "cursor": session_cursor},
    )
    assert session_mismatch.status_code == 400
    assert session_mismatch.json()["code"] == "INVALID_CURSOR"

    # 恰好取满也仍给游标，下一页为空（ADR-0082 决策 5）
    exact = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 3},
    )
    assert exact.status_code == 200
    assert exact.json()["next_cursor"]
    empty = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 3, "cursor": exact.json()["next_cursor"]},
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["next_cursor"] is None


async def test_session_pin_audits_reject_bad_params(client: AsyncClient) -> None:
    for params in (
        {"user_id": ""},
        {"session_id": ""},
        {"action": "delete"},
        {"limit": 0},
        {"limit": 201},
    ):
        res = await client.get("/api/admin/session-pins", headers=ADMIN, params=params)
        assert res.status_code == 422, params


async def test_session_pin_audits_return_503_on_store_failure(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    failing = AsyncMock(side_effect=SQLAlchemyError("boom"))
    monkeypatch.setattr(mem_store, "list_session_pin_audits", failing)
    res = await client.get("/api/admin/session-pins", headers=ADMIN)
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"
