"""工具配置变更历史（ADR-0037）：管理写入落审计、历史查询权限与失败语义。"""

from __future__ import annotations

from collections.abc import Sequence

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

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
    async def history(self, name: str, *, limit: int = 20) -> list[ToolSettingChangeRecord]:
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


async def test_history_requires_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/tools/query_cmdb/history", headers=EMPLOYEE)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_history_unknown_tool_is_empty_and_bad_limit(client: AsyncClient) -> None:
    # 工具下线/改名后历史仍可查；未知名字只是没有记录，不返回 404
    missing = await client.get("/api/admin/tools/ghost/history", headers=ADMIN)
    assert missing.status_code == 200
    assert missing.json() == {"items": []}

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
