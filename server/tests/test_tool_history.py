"""工具配置变更历史（ADR-0037）：管理写入落审计、历史查询权限与失败语义。"""

from __future__ import annotations

import base64
import hashlib
import json
import types
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.api import admin_tools
from app.api.admin_tools import (
    _decode_tool_history_cursor,
    _encode_tool_history_cursor,
    _history_fingerprint,
)
from app.api.errors import ApiError
from app.tools.policy import (
    InMemoryToolSettingStore,
    ToolOverride,
    ToolPolicy,
    ToolSettingChange,
    ToolSettingChangeRecord,
)
from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))
EMPLOYEE = auth_headers(user_id="u_102", roles=("employee",))


class _FailingHistoryStore:
    async def history(
        self,
        name: str,
        *,
        limit: int = 20,
        since: datetime | None = None,
        until: datetime | None = None,
        changed_by: str | None = None,
        source: str | None = None,
        before: tuple[datetime, int] | None = None,
        after: tuple[datetime, int] | None = None,
        order: str = "desc",
    ) -> list[ToolSettingChangeRecord]:
        raise SQLAlchemyError("database down")

    async def count_history(
        self,
        name: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        changed_by: str | None = None,
        source: str | None = None,
    ) -> int:
        raise SQLAlchemyError("database down")


async def _history(client: AsyncClient, name: str = "query_cmdb") -> list[dict[str, object]]:
    res = await client.get(f"/api/admin/tools/{name}/history", headers=ADMIN)
    assert res.status_code == 200
    return res.json()["items"]


async def test_patch_enable_records_change(client: AsyncClient) -> None:
    res = await client.patch("/api/admin/tools/query_cmdb", headers=ADMIN, json={"enabled": False})
    assert res.status_code == 200

    items = await _history(client)
    assert len(items) == 1
    item = items[0]
    assert item["tool_name"] == "query_cmdb"
    assert item["changed_by"] == "admin_1"
    assert item["source"] == "tool"
    assert item["before"] is None
    assert item["after"] == {"enabled": False, "roles": None}


async def test_noop_patch_does_not_record(client: AsyncClient) -> None:
    # enabled=True 是代码默认值：写回默认不是一次治理变更
    res = await client.patch("/api/admin/tools/query_cmdb", headers=ADMIN, json={"enabled": True})
    assert res.status_code == 200
    assert await _history(client) == []


async def test_matrix_records_only_changed_tools(client: AsyncClient) -> None:
    res = await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": True, "roles": ["admin"]}]},
    )
    assert res.status_code == 200

    items = await _history(client)
    assert len(items) == 1
    assert items[0]["source"] == "matrix"
    assert items[0]["before"] is None
    assert items[0]["after"] == {"enabled": None, "roles": ["admin"]}


async def test_matrix_noop_does_not_record(client: AsyncClient) -> None:
    res = await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={
            "tools": [
                {"name": "query_cmdb", "enabled": True, "roles": []},
                {"name": "create_ticket", "enabled": True, "roles": []},
            ]
        },
    )
    assert res.status_code == 200
    assert await _history(client) == []


async def test_rollback_restores_before_snapshot(client: AsyncClient) -> None:
    first = await client.patch(
        "/api/admin/tools/query_cmdb", headers=ADMIN, json={"enabled": False}
    )
    assert first.status_code == 200
    change_id = (await _history(client))[0]["id"]
    assert isinstance(change_id, int)

    res = await client.post(
        f"/api/admin/tools/query_cmdb/history/{change_id}/rollback", headers=ADMIN
    )
    assert res.status_code == 200
    body = res.json()
    assert body["overridden"] is False
    assert body["enabled"] is True

    items = await _history(client)
    assert len(items) == 2
    assert items[0]["before"] == {"enabled": False, "roles": None}
    assert items[0]["after"] is None

    # 回滚到同一状态不重复写历史
    res = await client.post(
        f"/api/admin/tools/query_cmdb/history/{change_id}/rollback", headers=ADMIN
    )
    assert res.status_code == 200
    assert len(await _history(client)) == 2


async def test_rollback_rejects_unknown_history_and_employee(client: AsyncClient) -> None:
    res = await client.post("/api/admin/tools/ghost/history/1/rollback", headers=ADMIN)
    assert res.status_code == 404
    assert res.json()["code"] == "TOOL_NOT_FOUND"

    res = await client.post("/api/admin/tools/query_cmdb/history/9999/rollback", headers=ADMIN)
    assert res.status_code == 404
    assert res.json()["code"] == "HISTORY_NOT_FOUND"

    res = await client.post("/api/admin/tools/query_cmdb/history/1/rollback", headers=EMPLOYEE)
    assert res.status_code == 403


async def test_history_requires_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/tools/query_cmdb/history", headers=EMPLOYEE)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_history_unknown_tool_is_empty_and_bad_limit(client: AsyncClient) -> None:
    # 工具下线/改名后历史仍可查；未知名字只是没有记录，不返回 404
    missing = await client.get("/api/admin/tools/ghost/history", headers=ADMIN)
    assert missing.status_code == 200
    assert missing.json() == {"items": [], "total": 0, "next_cursor": None}

    for limit in (0, 101):
        res = await client.get(f"/api/admin/tools/query_cmdb/history?limit={limit}", headers=ADMIN)
        assert res.status_code == 422


async def test_history_returns_503_when_store_fails(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    original = mem_tool_settings._store
    mem_tool_settings._store = _FailingHistoryStore()  # type: ignore[assignment]
    try:
        res = await client.get("/api/admin/tools/query_cmdb/history", headers=ADMIN)
    finally:
        mem_tool_settings._store = original  # type: ignore[assignment]
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"


async def test_in_memory_store_orders_and_limits_history() -> None:
    store = InMemoryToolSettingStore()
    first = ToolSettingChange(
        tool_name="query_cmdb",
        changed_by="admin_1",
        source="tool",
        before=None,
        after={"enabled": False, "roles": None},
    )
    second = ToolSettingChange(
        tool_name="query_cmdb",
        changed_by="admin_2",
        source="matrix",
        before={"enabled": False, "roles": None},
        after={"enabled": None, "roles": ["admin"]},
    )
    await store.upsert(
        "query_cmdb", ToolOverride(enabled=False), updated_by="admin_1", change=first
    )
    await store.replace(
        {"query_cmdb": ToolOverride(roles=("admin",))}, updated_by="admin_2", changes=[second]
    )

    assert [row.changed_by for row in await store.history("query_cmdb")] == ["admin_2", "admin_1"]
    assert [row.changed_by for row in await store.history("query_cmdb", limit=1)] == ["admin_2"]


async def test_replace_records_multiple_changes() -> None:
    store = InMemoryToolSettingStore()
    changes: Sequence[ToolSettingChange] = (
        ToolSettingChange(
            tool_name="query_cmdb",
            changed_by="admin_1",
            source="matrix",
            before=None,
            after={"enabled": None, "roles": ["admin"]},
        ),
        ToolSettingChange(
            tool_name="create_ticket",
            changed_by="admin_1",
            source="matrix",
            before={"enabled": False, "roles": None},
            after=None,
        ),
    )
    await store.replace(
        {"query_cmdb": ToolOverride(roles=("admin",))},
        updated_by="admin_1",
        changes=changes,
    )
    assert len(await store.history("query_cmdb")) == 1
    create_ticket = await store.history("create_ticket")
    assert create_ticket[0].after is None
    # 同一次矩阵提交的多条记录共享时间戳，避免倒序读出来出现伪顺序
    assert create_ticket[0].changed_at == (await store.history("query_cmdb"))[0].changed_at


async def test_in_memory_store_filters_history_by_window() -> None:
    store = InMemoryToolSettingStore()
    store._history.extend(
        [
            ToolSettingChangeRecord(
                id=1,
                tool_name="query_cmdb",
                changed_by="admin_1",
                changed_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
                source="tool",
                before=None,
                after={"enabled": False, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=2,
                tool_name="query_cmdb",
                changed_by="admin_2",
                changed_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
                source="matrix",
                before={"enabled": False, "roles": None},
                after={"enabled": True, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=3,
                tool_name="query_cmdb",
                changed_by="admin_3",
                changed_at=datetime(2026, 1, 3, 12, tzinfo=UTC),
                source="tool",
                before={"enabled": True, "roles": None},
                after={"enabled": False, "roles": None},
            ),
        ]
    )

    rows = await store.history(
        "query_cmdb",
        since=datetime(2026, 1, 2, tzinfo=UTC),
        until=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert [row.id for row in rows] == [2]
    assert [
        row.id for row in await store.history("query_cmdb", since=datetime(2026, 1, 2, tzinfo=UTC))
    ] == [3, 2]
    assert [
        row.id for row in await store.history("query_cmdb", until=datetime(2026, 1, 2, tzinfo=UTC))
    ] == [1]
    assert [row.id for row in await store.history("query_cmdb", changed_by="admin_2")] == [2]
    assert await store.count_history("query_cmdb", changed_by="admin_2") == 1
    assert await store.count_history("query_cmdb", changed_by="admin_2", source="tool") == 0


async def test_history_date_range_validation(client: AsyncClient) -> None:
    for query in (
        "changed_from=2026-01-01",
        "changed_to=2026-01-02",
        "changed_from=2026-01-02&changed_to=2026-01-01",
        "changed_from=2025-01-01&changed_to=2026-01-02",
        "changed_from=9999-12-31&changed_to=9999-12-31",
    ):
        res = await client.get(f"/api/admin/tools/query_cmdb/history?{query}", headers=ADMIN)
        assert res.status_code == 422, query
        assert res.json()["code"] == "INVALID_RANGE"


async def test_history_filters_by_date(client: AsyncClient, mem_tool_settings: ToolPolicy) -> None:
    store = mem_tool_settings._store
    assert isinstance(store, InMemoryToolSettingStore)
    store._history.extend(
        [
            ToolSettingChangeRecord(
                id=1,
                tool_name="query_cmdb",
                changed_by="admin_1",
                changed_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
                source="tool",
                before=None,
                after={"enabled": False, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=2,
                tool_name="query_cmdb",
                changed_by="admin_2",
                changed_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
                source="tool",
                before={"enabled": False, "roles": None},
                after={"enabled": True, "roles": None},
            ),
        ]
    )

    res = await client.get(
        "/api/admin/tools/query_cmdb/history?changed_from=2026-01-02&changed_to=2026-01-02",
        headers=ADMIN,
    )
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["changed_by"] for item in items] == ["admin_2"]


async def test_history_filters_by_changed_by_and_source(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    store = mem_tool_settings._store
    assert isinstance(store, InMemoryToolSettingStore)
    store._history.extend(
        [
            ToolSettingChangeRecord(
                id=1,
                tool_name="query_cmdb",
                changed_by="admin_2",
                changed_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
                source="tool",
                before=None,
                after={"enabled": False, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=2,
                tool_name="query_cmdb",
                changed_by="admin_1",
                changed_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
                source="tool",
                before={"enabled": False, "roles": None},
                after={"enabled": True, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=3,
                tool_name="query_cmdb",
                changed_by="admin_1",
                changed_at=datetime(2026, 1, 3, 12, tzinfo=UTC),
                source="matrix",
                before={"enabled": True, "roles": None},
                after={"enabled": None, "roles": ["admin"]},
            ),
        ]
    )

    by_admin = await client.get(
        "/api/admin/tools/query_cmdb/history?changed_by=admin_1",
        headers=ADMIN,
    )
    assert by_admin.status_code == 200
    body = by_admin.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [3, 2]

    matrix = await client.get(
        "/api/admin/tools/query_cmdb/history?changed_by=admin_1&source=matrix",
        headers=ADMIN,
    )
    assert matrix.status_code == 200
    assert [item["id"] for item in matrix.json()["items"]] == [3]

    empty = await client.get(
        "/api/admin/tools/query_cmdb/history?changed_by=admin_2&source=matrix",
        headers=ADMIN,
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0

    bad_source = await client.get(
        "/api/admin/tools/query_cmdb/history?source=api",
        headers=ADMIN,
    )
    assert bad_source.status_code == 422

    # 空串不是「未提供」：Query min_length=1 直接 422，避免把 "" 当成某个用户去查。
    empty_changed_by = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"changed_by": ""},
    )
    assert empty_changed_by.status_code == 422

    first = await client.get(
        "/api/admin/tools/query_cmdb/history?changed_by=admin_1&limit=1",
        headers=ADMIN,
    )
    cursor = first.json()["next_cursor"]
    assert cursor
    stale = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"changed_by": "admin_2", "limit": 1, "cursor": cursor},
    )
    assert stale.status_code == 400
    assert stale.json()["code"] == "INVALID_CURSOR"

    exported = await client.get(
        "/api/admin/tools/query_cmdb/history/export?changed_by=admin_1&source=matrix",
        headers=ADMIN,
    )
    assert exported.status_code == 200
    assert exported.headers["X-Export-Count"] == "1"
    assert "matrix" in exported.text


async def test_history_paginates_and_binds_cursor_to_filters(
    client: AsyncClient,
    mem_tool_settings: ToolPolicy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        admin_tools,
        "get_settings",
        lambda: types.SimpleNamespace(tool_history_cursor_ttl_s=120),
    )
    store = mem_tool_settings._store
    assert isinstance(store, InMemoryToolSettingStore)
    store._history.extend(
        [
            ToolSettingChangeRecord(
                id=1,
                tool_name="query_cmdb",
                changed_by="admin_1",
                changed_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
                source="tool",
                before=None,
                after={"enabled": False, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=2,
                tool_name="query_cmdb",
                changed_by="admin_2",
                changed_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
                source="tool",
                before={"enabled": False, "roles": None},
                after={"enabled": True, "roles": None},
            ),
            ToolSettingChangeRecord(
                id=3,
                tool_name="query_cmdb",
                changed_by="admin_3",
                changed_at=datetime(2026, 1, 3, 12, tzinfo=UTC),
                source="tool",
                before={"enabled": True, "roles": None},
                after={"enabled": False, "roles": None},
            ),
        ]
    )

    first = await client.get(
        "/api/admin/tools/query_cmdb/history", headers=ADMIN, params={"limit": 2}
    )
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == 3
    assert [item["id"] for item in page["items"]] == [3, 2]
    cursor = page["next_cursor"]
    assert isinstance(cursor, str) and cursor
    cursor_payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    remaining = cursor_payload["e"] - int(datetime.now(UTC).timestamp())
    assert 60 < remaining <= 120

    second = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": cursor},
    )
    assert second.status_code == 200
    page2 = second.json()
    assert page2["total"] is None
    assert [item["id"] for item in page2["items"]] == [1]
    assert page2["next_cursor"] is None

    earliest = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "order": "earliest"},
    )
    assert earliest.status_code == 200
    asc_page = earliest.json()
    assert asc_page["total"] == 3
    assert [item["id"] for item in asc_page["items"]] == [1, 2]
    asc_cursor = asc_page["next_cursor"]
    assert isinstance(asc_cursor, str) and asc_cursor

    asc_next = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "order": "earliest", "cursor": asc_cursor},
    )
    assert asc_next.status_code == 200
    asc_page2 = asc_next.json()
    assert asc_page2["total"] is None
    assert [item["id"] for item in asc_page2["items"]] == [3]
    assert asc_page2["next_cursor"] is None

    order_mismatch = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": asc_cursor},
    )
    assert order_mismatch.status_code == 400
    assert order_mismatch.json()["code"] == "INVALID_CURSOR"

    mismatch = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={
            "limit": 2,
            "cursor": cursor,
            "changed_from": "2026-01-01",
            "changed_to": "2026-01-03",
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "INVALID_CURSOR"

    malformed = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": "not-a-cursor"},
    )
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "INVALID_CURSOR"

    # 超长游标也应走 400，而不是 FastAPI 的 Query(max_length) 422。
    oversized = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": "x" * 600},
    )
    assert oversized.status_code == 400
    assert oversized.json()["code"] == "INVALID_CURSOR"

    # 过期游标单独返回 CURSOR_EXPIRED；客户端应提示重新加载，而不是从头开始。
    fingerprint = _history_fingerprint("query_cmdb", None, None, None, None, "latest")
    expired_raw = json.dumps(
        {
            "t": "2026-01-02T12:00:00+00:00",
            "i": 2,
            "f": fingerprint,
            "e": 1,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    expired_cursor = base64.urlsafe_b64encode(expired_raw).decode("ascii")
    expired = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": expired_cursor},
    )
    assert expired.status_code == 400
    assert expired.json()["code"] == "CURSOR_EXPIRED"

    # 旧版本游标没有 e，不能猜一个 TTL；必须明确失效。
    legacy_raw = json.dumps(
        {"t": "2026-01-02T12:00:00+00:00", "i": 2, "f": fingerprint},
        separators=(",", ":"),
    ).encode("utf-8")
    legacy_cursor = base64.urlsafe_b64encode(legacy_raw).decode("ascii")
    legacy = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": legacy_cursor},
    )
    assert legacy.status_code == 400
    assert legacy.json()["code"] == "INVALID_CURSOR"

    # 过大指数会解析成 inf，int(inf) 抛 OverflowError，也应走 400 而不是 500。
    infinite_raw = json.dumps(
        {
            "t": "2026-01-02T12:00:00+00:00",
            "i": 2,
            "f": fingerprint,
            "e": 1e309,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    infinite_cursor = base64.urlsafe_b64encode(infinite_raw).decode("ascii")
    infinite = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": infinite_cursor},
    )
    assert infinite.status_code == 400
    assert infinite.json()["code"] == "INVALID_CURSOR"

    # e 必须是整数秒；1.5 不能靠 int() 截断成 1 秒后被放过。
    fractional_raw = json.dumps(
        {
            "t": "2026-01-02T12:00:00+00:00",
            "i": 2,
            "f": fingerprint,
            "e": 1.5,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    fractional_cursor = base64.urlsafe_b64encode(fractional_raw).decode("ascii")
    fractional = await client.get(
        "/api/admin/tools/query_cmdb/history",
        headers=ADMIN,
        params={"limit": 2, "cursor": fractional_cursor},
    )
    assert fractional.status_code == 400
    assert fractional.json()["code"] == "INVALID_CURSOR"


async def test_history_export_records_download(client: AsyncClient) -> None:
    for enabled in (False, True):
        res = await client.patch(
            "/api/admin/tools/query_cmdb", headers=ADMIN, json={"enabled": enabled}
        )
        assert res.status_code == 200

    forbidden = await client.get("/api/admin/tools/query_cmdb/history/export", headers=EMPLOYEE)
    assert forbidden.status_code == 403

    bad_range = await client.get(
        "/api/admin/tools/query_cmdb/history/export?changed_from=2026-01-02",
        headers=ADMIN,
    )
    assert bad_range.status_code == 422
    assert bad_range.json()["code"] == "INVALID_RANGE"

    res = await client.get("/api/admin/tools/query_cmdb/history/export", headers=ADMIN)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["x-export-count"] == "2"
    assert res.headers["x-export-truncated"] == "false"
    body = res.text
    assert body.startswith("\ufefftool_name,changed_at,changed_by,source,before,after")
    assert "query_cmdb" in body

    audited = await client.get(
        "/api/admin/export-audits?resource=tool_setting_history", headers=ADMIN
    )
    assert audited.status_code == 200
    payload = audited.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["resource"] == "tool_setting_history"
    assert item["filters"] == {"tool": "query_cmdb"}
    assert item["row_count"] == 2
    assert item["truncated"] is False
    assert item["content_sha256"] == hashlib.sha256(res.content).hexdigest()

    # 工具名来自 URL，可能含非 ASCII；文件名必须能安全写进 latin-1 响应头
    non_ascii = await client.get(
        "/api/admin/tools/%E5%B7%A5%E5%85%B7/history/export", headers=ADMIN
    )
    assert non_ascii.status_code == 200
    assert non_ascii.headers["content-disposition"].isascii()


def test_cursor_ttl_is_adjustable() -> None:
    """TTL 由配置传入，默认 60 分钟；边界秒仍有效，超过才过期（ADR-0105）。"""
    record = ToolSettingChangeRecord(
        id=7,
        tool_name="query_cmdb",
        changed_by="admin_1",
        changed_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
        source="tool",
        before=None,
        after={"enabled": True, "roles": None},
    )
    fingerprint = _history_fingerprint("query_cmdb", None, None, None, None, "latest")
    issued_at = datetime(2026, 1, 2, 12, tzinfo=UTC)
    cursor = _encode_tool_history_cursor(record, fingerprint, now=issued_at, ttl_s=120)

    assert _decode_tool_history_cursor(cursor, fingerprint, now=issued_at) == (
        record.changed_at,
        record.id,
    )
    assert _decode_tool_history_cursor(
        cursor, fingerprint, now=issued_at + timedelta(seconds=120)
    ) == (record.changed_at, record.id)
    with pytest.raises(ApiError) as exc:
        _decode_tool_history_cursor(cursor, fingerprint, now=issued_at + timedelta(seconds=121))
    assert exc.value.code == "CURSOR_EXPIRED"
