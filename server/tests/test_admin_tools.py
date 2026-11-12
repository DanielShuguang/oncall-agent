"""工具注册、试调用与权限矩阵（W5 D22/D23）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.agent.deps import AgentDeps
from app.agent.nodes.plan import plan_node
from app.agent.state import initial_state
from app.tools.assets import InMemoryAssetRepository
from app.tools.builtin import default_registry
from app.tools.policy import ToolOverride, ToolPolicy
from app.tools.registry import Identity, ToolGuard
from app.tools.tickets import InMemoryTicketRepository
from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))


class _FailingStore:
    """策略存储不可用：管理接口应 503，而不是拿空快照覆盖。"""

    async def load(self) -> dict[str, ToolOverride]:
        raise SQLAlchemyError("database down")

    async def upsert(self, name: str, override: ToolOverride | None, *, updated_by: str) -> None:
        raise SQLAlchemyError("database down")

    async def replace(self, overrides: Mapping[str, ToolOverride], *, updated_by: str) -> None:
        raise SQLAlchemyError("database down")


async def test_list_tools_requires_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/tools")
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_list_tools_includes_governance_metadata(client: AsyncClient) -> None:
    res = await client.get("/api/admin/tools", headers=ADMIN)
    assert res.status_code == 200
    tools = {item["name"]: item for item in res.json()["items"]}
    assert set(tools) == {"query_cmdb", "query_tickets", "create_ticket"}
    assert tools["query_cmdb"]["is_write"] is False
    assert tools["query_cmdb"]["enabled"] is True
    assert tools["create_ticket"]["is_write"] is True
    assert "title" in tools["create_ticket"]["input_schema"]["required"]


async def test_test_read_tool_goes_through_guard(
    client: AsyncClient, mem_assets: InMemoryAssetRepository
) -> None:
    mem_assets.add(
        {
            "asset_id": "PC-90001",
            "owner_id": "admin_1",
            "type": "laptop",
            "model": "ThinkPad X1",
            "location": "5F",
            "ip": "10.20.99.1",
            "warranty_until": "2028-01-01",
            "status": "online",
        }
    )
    res = await client.post(
        "/api/admin/tools/query_cmdb/test",
        headers=ADMIN,
        json={"args": {}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] == "executed"
    assert body["status"] == "ok"
    assert body["result"]["assets"][0]["asset_id"] == "PC-90001"


async def test_test_tool_rejects_reserved_identity_args(client: AsyncClient) -> None:
    res = await client.post(
        "/api/admin/tools/query_cmdb/test",
        headers=ADMIN,
        json={"args": {"asset_id": "PC-20481", "user_id": "admin_1"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] == "denied"
    assert body["error_kind"] == "permission"
    assert "身份字段" in body["error"]


async def test_write_tool_test_call_only_requests_approval(
    client: AsyncClient, mem_tickets: InMemoryTicketRepository
) -> None:
    res = await client.post(
        "/api/admin/tools/create_ticket/test",
        headers=ADMIN,
        json={"args": {"title": "打印机离线", "category": "hardware", "priority": "P2"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] == "requires_approval"
    assert body["status"] == "requires_approval"
    assert body["result"] is None
    # 试调用绝不能借管理页真的落单
    assert mem_tickets.count() == 0


async def test_unknown_tool_returns_404(client: AsyncClient) -> None:
    res = await client.post(
        "/api/admin/tools/not_a_tool/test",
        headers=ADMIN,
        json={"args": {}},
    )
    assert res.status_code == 404
    assert res.json()["code"] == "TOOL_NOT_FOUND"


async def test_disable_tool_blocks_execution_and_can_be_restored(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    disabled = await client.patch(
        "/api/admin/tools/query_cmdb",
        headers=ADMIN,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["overridden"] is True

    blocked = await client.post(
        "/api/admin/tools/query_cmdb/test",
        headers=ADMIN,
        json={"args": {}},
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "denied"
    assert blocked.json()["error"] == "工具已禁用"

    restored = await client.patch(
        "/api/admin/tools/query_cmdb",
        headers=ADMIN,
        json={"enabled": None},
    )
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True
    assert restored.json()["overridden"] is False
    assert await mem_tool_settings.override_for("query_cmdb") is None


async def test_enabling_back_to_default_clears_override(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    await client.patch("/api/admin/tools/query_cmdb", headers=ADMIN, json={"enabled": False})
    restored = await client.patch(
        "/api/admin/tools/query_cmdb",
        headers=ADMIN,
        json={"enabled": True},
    )
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True
    assert restored.json()["overridden"] is False
    assert await mem_tool_settings.override_for("query_cmdb") is None


async def test_perm_matrix_lists_roles_and_tools(client: AsyncClient) -> None:
    res = await client.get("/api/admin/perm-matrix", headers=ADMIN)
    assert res.status_code == 200
    body = res.json()
    assert set(body["roles"]) >= {"employee", "approver", "admin"}
    assert {tool["name"] for tool in body["tools"]} == {
        "query_cmdb",
        "query_tickets",
        "create_ticket",
    }


async def test_perm_matrix_update_restricts_tool_to_admin(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    res = await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": True, "roles": ["admin"]}]},
    )
    assert res.status_code == 200
    tool = next(item for item in res.json()["tools"] if item["name"] == "query_cmdb")
    assert tool["roles"] == ["admin"]
    assert tool["overridden"] is True

    guard = ToolGuard(default_registry(), policy=mem_tool_settings)
    employee = Identity(user_id="u_102", roles=frozenset({"employee"}))
    denied = await guard.execute("query_cmdb", {}, employee, call_id="call_1")
    assert denied.status.value == "denied"

    admin = Identity(user_id="admin_1", roles=frozenset({"admin"}))
    allowed = await guard.execute("query_cmdb", {}, admin, call_id="call_2")
    assert allowed.status.value == "ok"


async def test_perm_matrix_can_reset_to_code_defaults(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": True, "roles": []}]},
    )
    assert await mem_tool_settings.override_for("query_cmdb") is None


async def test_resetting_enabled_keeps_role_override(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": False, "roles": ["admin"]}]},
    )
    await client.patch(
        "/api/admin/tools/query_cmdb",
        headers=ADMIN,
        json={"enabled": None},
    )
    override = await mem_tool_settings.override_for("query_cmdb")
    assert override is not None
    assert override.enabled is None
    assert override.roles == ("admin",)


async def test_perm_matrix_rejects_unknown_role_and_tool(client: AsyncClient) -> None:
    bad_role = await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": True, "roles": ["root"]}]},
    )
    assert bad_role.status_code == 422
    assert bad_role.json()["code"] == "INVALID_ARGS"

    bad_tool = await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "ghost", "enabled": True, "roles": []}]},
    )
    assert bad_tool.status_code == 422


async def test_policy_cannot_enable_code_disabled_tool() -> None:
    locked = replace(default_registry().require("query_cmdb"), enabled=False)
    effective = ToolPolicy.effective_spec(locked, ToolOverride(enabled=True))
    assert effective.enabled is False


async def test_admin_read_returns_503_when_policy_unreadable(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    original = mem_tool_settings._store  # 注入故障存储，验证失败语义
    mem_tool_settings._store = _FailingStore()  # type: ignore[assignment]
    try:
        tools = await client.get("/api/admin/tools", headers=ADMIN)
        matrix = await client.get("/api/admin/perm-matrix", headers=ADMIN)
    finally:
        mem_tool_settings._store = original  # type: ignore[assignment]
    assert tools.status_code == 503
    assert matrix.status_code == 503


async def test_perm_matrix_read_failure_does_not_wipe_overrides(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": True, "roles": ["admin"]}]},
    )
    original = mem_tool_settings._store
    mem_tool_settings._store = _FailingStore()  # type: ignore[assignment]
    try:
        failed = await client.put(
            "/api/admin/perm-matrix",
            headers=ADMIN,
            json={"tools": [{"name": "create_ticket", "enabled": False, "roles": []}]},
        )
    finally:
        mem_tool_settings._store = original  # type: ignore[assignment]
        mem_tool_settings.invalidate()
    assert failed.status_code == 503
    # 关键：读失败的那次保存没有进入 replace，原有角色覆盖还在
    override = await mem_tool_settings.override_for("query_cmdb")
    assert override is not None
    assert override.roles == ("admin",)


async def test_partial_matrix_update_keeps_other_overrides(
    client: AsyncClient, mem_tool_settings: ToolPolicy
) -> None:
    await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "query_cmdb", "enabled": True, "roles": ["admin"]}]},
    )
    await client.put(
        "/api/admin/perm-matrix",
        headers=ADMIN,
        json={"tools": [{"name": "create_ticket", "enabled": False, "roles": []}]},
    )
    override = await mem_tool_settings.override_for("query_cmdb")
    assert override is not None
    assert override.roles == ("admin",)


async def test_admin_requests_reject_unknown_fields(client: AsyncClient) -> None:
    patch = await client.patch(
        "/api/admin/tools/query_cmdb",
        headers=ADMIN,
        json={"enabled": True, "roles": ["admin"]},
    )
    test = await client.post(
        "/api/admin/tools/query_cmdb/test",
        headers=ADMIN,
        json={"args": {}, "unexpected": 1},
    )
    assert patch.status_code == 422
    assert test.status_code == 422


async def test_plan_skips_tools_removed_by_policy(
    mem_tool_settings: ToolPolicy,
) -> None:
    """管理端禁用后，规则计划也不能继续把该工具送进 act。"""
    await mem_tool_settings.set_override("query_cmdb", ToolOverride(enabled=False))
    deps = AgentDeps(
        guard=ToolGuard(default_registry(), policy=mem_tool_settings),
        gateway=None,
    )
    state = initial_state(
        run_id="r1",
        user={"id": "u_102", "roles": ["employee"]},
        query="我电脑连不上打印机了",
    )
    state.update({"intent": "asset_check", "incident_type": "hardware"})

    delta = await plan_node(state, deps)

    assert delta["plan"] == []
    assert delta["plan_source"] == "rule"
