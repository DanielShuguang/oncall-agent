"""会话置顶审计的管理端读取（ADR-0081）。"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
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
    for path in (
        "/api/admin/session-pins",
        "/api/admin/session-pins/export",
        "/api/admin/session-pins/stats",
    ):
        res = await client.get(path)
        assert res.status_code == 403
        assert res.json()["code"] == "FORBIDDEN"


async def test_list_session_pin_audits(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    await _pin_once(mem_store, user_id="u_102", session_id="sess_a")
    await asyncio.sleep(0.002)
    await _pin_once(mem_store, user_id="u_103", session_id="sess_b")
    await asyncio.sleep(0.002)
    assert await mem_store.unpin_session(user_id="u_102", session_id="sess_a") is True

    res = await client.get("/api/admin/session-pins", headers=ADMIN)
    assert res.status_code == 200
    assert res.json()["total"] == 3
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
    assert filtered.json()["total"] == 1
    assert [item["session_id"] for item in filtered.json()["items"]] == ["sess_a"]
    by_session = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"session_id": "sess_a"},
    )
    assert by_session.status_code == 200
    assert by_session.json()["total"] == 2
    assert [item["action"] for item in by_session.json()["items"]] == ["unpin", "pin"]
    limited = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 1},
    )
    assert limited.status_code == 200
    assert limited.json()["total"] == 3
    assert len(limited.json()["items"]) == 1

    # 计数与列表之间新增了审计：total < 当前页条数时按「未知」处理，
    # 不能显示「共 0 条 · 已加载 3 条」。
    original_count = mem_store.count_session_pin_audits
    monkeypatch.setattr(mem_store, "count_session_pin_audits", AsyncMock(return_value=0))
    try:
        inconsistent = await client.get("/api/admin/session-pins", headers=ADMIN)
        assert inconsistent.status_code == 200
        assert inconsistent.json()["total"] is None
        assert len(inconsistent.json()["items"]) == 3
    finally:
        monkeypatch.setattr(mem_store, "count_session_pin_audits", original_count)


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
    assert first_body["total"] == 3
    assert first_body["next_cursor"]

    second = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["total"] is None
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
    assert filtered.json()["total"] == 2
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

    # 过滤条件只进指纹，不把最多 64 字符的原始 id 塞进游标；否则非 ASCII id
    # 经 \uXXXX 转义 + base64 后可能超过 512 上限，下一页直接 422。
    long_user = "用" * 64
    long_session = "会" * 64
    await _pin_once(mem_store, user_id=long_user, session_id=long_session)
    assert await mem_store.unpin_session(user_id=long_user, session_id=long_session) is True
    long_first = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={"user_id": long_user, "session_id": long_session, "limit": 1},
    )
    assert long_first.status_code == 200
    long_cursor = long_first.json()["next_cursor"]
    assert long_cursor
    assert len(long_cursor) <= 512
    long_second = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={
            "user_id": long_user,
            "session_id": long_session,
            "limit": 1,
            "cursor": long_cursor,
        },
    )
    assert long_second.status_code == 200
    assert {item["id"] for item in long_first.json()["items"]} & {
        item["id"] for item in long_second.json()["items"]
    } == set()


async def test_session_pin_audit_date_range(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _pin_once(mem_store, user_id="u_102", session_id="sess_a")
    assert await mem_store.unpin_session(user_id="u_102", session_id="sess_a") is True
    audits = await mem_store.list_session_pin_audits(user_id="u_102", limit=10)
    days = sorted({record.created_at.date() for record in audits})
    day_from = days[0]
    day_to = days[-1]
    tomorrow = day_to + timedelta(days=1)

    by_range = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={
            "created_from": day_from.isoformat(),
            "created_to": day_to.isoformat(),
        },
    )
    assert by_range.status_code == 200
    assert by_range.json()["total"] == 2
    assert len(by_range.json()["items"]) == 2

    by_tomorrow = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={
            "created_from": tomorrow.isoformat(),
            "created_to": tomorrow.isoformat(),
        },
    )
    assert by_tomorrow.status_code == 200
    assert by_tomorrow.json()["total"] == 0
    assert by_tomorrow.json()["items"] == []

    across_days = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={
            "created_from": (day_from - timedelta(days=1)).isoformat(),
            "created_to": day_to.isoformat(),
        },
    )
    assert across_days.status_code == 200
    assert across_days.json()["total"] == 2
    assert len(across_days.json()["items"]) == 2

    first = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={
            "created_from": day_from.isoformat(),
            "created_to": day_to.isoformat(),
            "limit": 1,
        },
    )
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor
    mismatched = await client.get(
        "/api/admin/session-pins",
        headers=ADMIN,
        params={
            "created_from": tomorrow.isoformat(),
            "created_to": tomorrow.isoformat(),
            "cursor": cursor,
        },
    )
    assert mismatched.status_code == 400
    assert mismatched.json()["code"] == "INVALID_CURSOR"

    for params in (
        {"created_from": day_from.isoformat()},
        {
            "created_from": tomorrow.isoformat(),
            "created_to": day_from.isoformat(),
        },
        {
            "created_from": (day_to - timedelta(days=365)).isoformat(),
            "created_to": day_to.isoformat(),
        },
        {"created_from": "9999-12-31", "created_to": "9999-12-31"},
    ):
        res = await client.get("/api/admin/session-pins", headers=ADMIN, params=params)
        assert res.status_code == 422, params
        assert res.json()["code"] == "INVALID_RANGE"

    exported = await client.get(
        "/api/admin/session-pins/export",
        headers=ADMIN,
        params={
            "created_from": day_from.isoformat(),
            "created_to": day_to.isoformat(),
        },
    )
    assert exported.status_code == 200
    assert exported.headers["x-export-count"] == "2"
    empty = await client.get(
        "/api/admin/session-pins/export",
        headers=ADMIN,
        params={
            "created_from": tomorrow.isoformat(),
            "created_to": tomorrow.isoformat(),
        },
    )
    assert empty.status_code == 200
    assert empty.headers["x-export-count"] == "0"
    bad_export = await client.get(
        "/api/admin/session-pins/export",
        headers=ADMIN,
        params={"created_from": day_from.isoformat()},
    )
    assert bad_export.status_code == 422
    assert bad_export.json()["code"] == "INVALID_RANGE"


async def test_export_session_pin_audits_csv(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _pin_once(mem_store, user_id="u_102", session_id="sess_a")
    await asyncio.sleep(0.002)
    await _pin_once(mem_store, user_id="u_103", session_id="sess_b")
    await asyncio.sleep(0.002)
    assert await mem_store.unpin_session(user_id="u_102", session_id="sess_a") is True

    res = await client.get("/api/admin/session-pins/export", headers=ADMIN)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-export-count"] == "3"
    assert res.headers["x-export-truncated"] == "false"
    assert "attachment; filename=" in res.headers["content-disposition"]
    assert res.text.startswith("\ufeff")
    assert "\r\n" in res.text

    rows = list(csv.reader(io.StringIO(res.text.lstrip("\ufeff"))))
    assert rows[0] == ["audit_id", "user_id", "session_id", "action", "created_at"]
    assert [(row[1], row[2], row[3]) for row in rows[1:]] == [
        ("u_102", "sess_a", "unpin"),
        ("u_103", "sess_b", "pin"),
        ("u_102", "sess_a", "pin"),
    ]

    filtered = await client.get(
        "/api/admin/session-pins/export",
        headers=ADMIN,
        params={"action": "pin"},
    )
    assert filtered.status_code == 200
    assert filtered.headers["x-export-count"] == "2"
    filtered_rows = list(csv.reader(io.StringIO(filtered.text.lstrip("\ufeff"))))
    assert [row[3] for row in filtered_rows[1:]] == ["pin", "pin"]

    # 共享 csv_cell 的公式注入防护：admin 导出的用户字段也不能以 = 开头。
    await _pin_once(mem_store, user_id="=cmd", session_id="sess_formula")
    formula = await client.get(
        "/api/admin/session-pins/export",
        headers=ADMIN,
        params={"user_id": "=cmd"},
    )
    assert formula.status_code == 200
    formula_rows = list(csv.reader(io.StringIO(formula.text.lstrip("\ufeff"))))
    assert formula_rows[1][1] == "'=cmd"


async def test_export_session_pin_audits_truncates(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    monkeypatch.setattr("app.api.admin_pins.MAX_EXPORT_ROWS", 2)
    for index in range(3):
        await _pin_once(mem_store, user_id="u_102", session_id=f"sess_{index}")

    res = await client.get("/api/admin/session-pins/export", headers=ADMIN)
    assert res.status_code == 200
    assert res.headers["x-export-count"] == "2"
    assert res.headers["x-export-truncated"] == "true"
    rows = list(csv.reader(io.StringIO(res.text.lstrip("\ufeff"))))
    assert len(rows) == 3


async def test_session_pin_audit_stats(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    await _pin_once(mem_store, user_id="u_102", session_id="sess_a")
    await asyncio.sleep(0.002)
    await _pin_once(mem_store, user_id="u_103", session_id="sess_b")
    assert await mem_store.unpin_session(user_id="u_102", session_id="sess_a") is True

    res = await client.get(
        "/api/admin/session-pins/stats",
        headers=ADMIN,
        params={"days": 7},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["days"] == 7
    assert body["since"] and body["until"]
    assert (body["pins"], body["unpins"], body["users"], body["sessions"]) == (2, 1, 2, 2)
    assert len(body["daily"]) == 1
    assert body["daily"][0]["pins"] == 2
    assert body["daily"][0]["unpins"] == 1
    for params in ({"days": 0}, {"days": 366}):
        bad = await client.get("/api/admin/session-pins/stats", headers=ADMIN, params=params)
        assert bad.status_code == 422

    filtered = await client.get(
        "/api/admin/session-pins/stats",
        headers=ADMIN,
        params={"days": 7, "user_id": "u_102"},
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert (filtered_body["pins"], filtered_body["unpins"]) == (1, 1)
    assert (filtered_body["users"], filtered_body["sessions"]) == (1, 1)

    pin_only = await client.get(
        "/api/admin/session-pins/stats",
        headers=ADMIN,
        params={"days": 7, "action": "pin"},
    )
    assert pin_only.status_code == 200
    assert (pin_only.json()["pins"], pin_only.json()["unpins"]) == (2, 0)

    today = datetime.now(UTC).date().isoformat()
    ranged = await client.get(
        "/api/admin/session-pins/stats",
        headers=ADMIN,
        params={"created_from": today, "created_to": today, "user_id": "u_102"},
    )
    assert ranged.status_code == 200
    ranged_body = ranged.json()
    assert ranged_body["days"] == 1
    assert (ranged_body["pins"], ranged_body["unpins"]) == (1, 1)

    both = await client.get(
        "/api/admin/session-pins/stats",
        headers=ADMIN,
        params={"days": 7, "created_from": today, "created_to": today},
    )
    assert both.status_code == 422
    assert both.json()["code"] == "INVALID_RANGE"

    half = await client.get(
        "/api/admin/session-pins/stats",
        headers=ADMIN,
        params={"created_from": today},
    )
    assert half.status_code == 422
    assert half.json()["code"] == "INVALID_RANGE"


async def test_session_pin_audits_reject_bad_params(client: AsyncClient) -> None:
    for path in (
        "/api/admin/session-pins",
        "/api/admin/session-pins/export",
        "/api/admin/session-pins/stats",
    ):
        for params in ({"user_id": ""}, {"session_id": ""}, {"action": "delete"}):
            res = await client.get(path, headers=ADMIN, params=params)
            assert res.status_code == 422, (path, params)
    for params in ({"limit": 0}, {"limit": 201}):
        res = await client.get("/api/admin/session-pins", headers=ADMIN, params=params)
        assert res.status_code == 422, params


async def test_session_pin_audits_return_503_on_store_failure(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    failing = AsyncMock(side_effect=SQLAlchemyError("boom"))
    original_count = mem_store.count_session_pin_audits
    monkeypatch.setattr(mem_store, "count_session_pin_audits", failing)
    count_failed = await client.get("/api/admin/session-pins", headers=ADMIN)
    assert count_failed.status_code == 503
    assert count_failed.json()["code"] == "DATABASE_UNAVAILABLE"
    monkeypatch.setattr(mem_store, "count_session_pin_audits", original_count)
    monkeypatch.setattr(mem_store, "list_session_pin_audits", failing)
    monkeypatch.setattr(mem_store, "session_pin_audit_stats", failing)
    for path in (
        "/api/admin/session-pins",
        "/api/admin/session-pins/export",
        "/api/admin/session-pins/stats",
    ):
        res = await client.get(path, headers=ADMIN)
        assert res.status_code == 503
        assert res.json()["code"] == "DATABASE_UNAVAILABLE"
