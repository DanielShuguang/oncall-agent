"""会话恢复审计的管理端读取（ADR-0059）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore
from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))


async def _restore_once(store: InMemoryRunStore, *, user_id: str, session_id: str) -> None:
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        message="打印机离线",
    )
    assert await store.hide_session(user_id=user_id, session_id=session_id) is True
    assert await store.unhide_session(user_id=user_id, session_id=session_id) is True


async def test_session_restore_audits_require_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/session-restores")
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_list_session_restore_audits(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _restore_once(mem_store, user_id="u_102", session_id="sess_a")
    await _restore_once(mem_store, user_id="u_103", session_id="sess_b")

    res = await client.get("/api/admin/session-restores", headers=ADMIN)
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["user_id"] for item in items] == ["u_103", "u_102"]
    assert items[0]["session_ids"] == ["sess_b"]
    assert items[0]["requested_count"] == 1
    assert items[0]["restored_count"] == 1
    assert items[0]["restored_at"]

    filtered = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"user_id": "u_102"},
    )
    assert filtered.status_code == 200
    assert [item["user_id"] for item in filtered.json()["items"]] == ["u_102"]

    limited = await client.get("/api/admin/session-restores", headers=ADMIN, params={"limit": 1})
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1


async def test_session_restore_audits_reject_bad_params(client: AsyncClient) -> None:
    assert (
        await client.get("/api/admin/session-restores", headers=ADMIN, params={"limit": 0})
    ).status_code == 422
    assert (
        await client.get(
            "/api/admin/session-restores",
            headers=ADMIN,
            params={"user_id": "x" * 65},
        )
    ).status_code == 422


async def test_session_restore_audits_return_503_on_store_failure(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    monkeypatch.setattr(
        mem_store,
        "list_session_restore_audits",
        AsyncMock(side_effect=SQLAlchemyError("database down")),
    )
    res = await client.get("/api/admin/session-restores", headers=ADMIN)
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"
