"""会话恢复审计的管理端读取（ADR-0059）。"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore, SessionRestoreAuditRecord
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
    await asyncio.sleep(0.002)
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


async def test_session_restore_audits_paginate(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    for index in range(3):
        await _restore_once(mem_store, user_id="u_102", session_id=f"sess_page_{index}")
        await asyncio.sleep(0.002)
    await _restore_once(mem_store, user_id="u_200", session_id="sess_other_user")

    first = await client.get("/api/admin/session-restores", headers=ADMIN, params={"limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"]

    second = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 2
    assert second_body["next_cursor"]

    third = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"limit": 2, "cursor": second_body["next_cursor"]},
    )
    assert third.status_code == 200
    third_body = third.json()
    assert len(third_body["items"]) == 0
    assert third_body["next_cursor"] is None

    all_ids = [
        item["id"] for item in first_body["items"] + second_body["items"] + third_body["items"]
    ]
    assert len(all_ids) == len(set(all_ids)) == 4

    # 同一 restored_at 时按 id 倒序；游标里的 UUID 大小写不影响位置
    tie_time = datetime(2026, 11, 14, tzinfo=UTC)
    tie_ids = [str(uuid.UUID(int=index)) for index in (2, 3)]
    mem_store._session_restore_audits.extend(
        [
            SessionRestoreAuditRecord(
                audit_id=audit_id,
                user_id="u_300",
                session_ids=(f"sess_tie_{audit_id[-4:]}",),
                requested_count=1,
                restored_count=1,
                restored_at=tie_time,
            )
            for audit_id in tie_ids
        ]
    )

    tie_first = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"user_id": "u_300", "limit": 1},
    )
    assert tie_first.status_code == 200
    tie_first_body = tie_first.json()
    assert [item["id"] for item in tie_first_body["items"]] == [tie_ids[1]]

    # 把游标里的 UUID 改成大写；归一化后仍能从同一位置继续
    raw = base64.urlsafe_b64decode(tie_first_body["next_cursor"] + "==")
    payload = json.loads(raw)
    payload["i"] = payload["i"].upper()
    upper_cursor = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    tie_second = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"user_id": "u_300", "limit": 1, "cursor": upper_cursor},
    )
    assert tie_second.status_code == 200
    tie_second_body = tie_second.json()
    assert [item["id"] for item in tie_second_body["items"]] == [tie_ids[0]]

    tie_third = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"user_id": "u_300", "limit": 1, "cursor": tie_second_body["next_cursor"]},
    )
    assert tie_third.status_code == 200
    assert tie_third.json()["items"] == []
    assert tie_third.json()["next_cursor"] is None

    bad_cursor = await client.get(
        "/api/admin/session-restores", headers=ADMIN, params={"cursor": "not-a-cursor"}
    )
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["code"] == "INVALID_CURSOR"

    # 游标绑定 user_id：全量游标不能复用到按用户过滤的请求
    mismatch = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"user_id": "u_102", "cursor": first_body["next_cursor"]},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "INVALID_CURSOR"


async def test_session_restore_audits_filter_by_session(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _restore_once(mem_store, user_id="u_102", session_id="sess_a")
    await asyncio.sleep(0.002)
    await _restore_once(mem_store, user_id="u_102", session_id="sess_b")
    await asyncio.sleep(0.002)
    await _restore_once(mem_store, user_id="u_200", session_id="sess_a")

    first = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"session_id": "sess_a", "limit": 1},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert [item["user_id"] for item in first_body["items"]] == ["u_200"]
    assert first_body["items"][0]["session_ids"] == ["sess_a"]
    assert first_body["next_cursor"]

    second = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"session_id": "sess_a", "limit": 1, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["user_id"] for item in second_body["items"]] == ["u_102"]
    assert second_body["items"][0]["session_ids"] == ["sess_a"]

    third = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"session_id": "sess_a", "limit": 1, "cursor": second_body["next_cursor"]},
    )
    assert third.status_code == 200
    assert third.json()["items"] == []
    assert third.json()["next_cursor"] is None

    missing = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"session_id": "sess_missing"},
    )
    assert missing.status_code == 200
    assert missing.json()["items"] == []

    # 游标绑定 session 过滤：同用户、换 session_id 也必须 400
    mismatch = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"session_id": "sess_b", "cursor": first_body["next_cursor"]},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "INVALID_CURSOR"

    # ADR-0060 旧游标没有 `s`；没有 session 过滤时仍然可用
    legacy_body = await client.get(
        "/api/admin/session-restores", headers=ADMIN, params={"limit": 1}
    )
    raw = base64.urlsafe_b64decode(legacy_body.json()["next_cursor"] + "==")
    legacy_payload = json.loads(raw)
    legacy_payload.pop("s")
    legacy_cursor = (
        base64.urlsafe_b64encode(json.dumps(legacy_payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    legacy = await client.get(
        "/api/admin/session-restores",
        headers=ADMIN,
        params={"limit": 1, "cursor": legacy_cursor},
    )
    assert legacy.status_code == 200


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
    assert (
        await client.get(
            "/api/admin/session-restores",
            headers=ADMIN,
            params={"session_id": "x" * 65},
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
