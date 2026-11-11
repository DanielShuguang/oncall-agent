"""v1 内置工具的实现与注册（W1 D5 用内存假数据）。

治理逻辑全部在 `registry.py`（R3），这里只负责「工具做什么」：

- `query_cmdb`：查用户名下资产。W1 用内存假数据，接真实 CMDB 时只替换 handler，
  `input_schema` / 超时 / 角色约束不变，治理链路不用动（docs/06 §8.2）。
- `create_ticket`：写操作，**永远不在这里判断能不能执行** —— 由 `ToolGuard` 挂起
  等审批（R10），审批通过后 runtime 用 `allow_write=True` 才走到 handler。
  requester 由 ToolGuard 注入服务端身份，不来自模型参数（R9）。

⚠️ `query_cmdb` 仍是假数据，不是从 CMDB 拉的，演示时不要当成真实资产；
W4 接真实 CMDB 时只替换 handler 与 input_schema。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.tools.registry import Identity, ToolError, ToolErrorKind, ToolRegistry, ToolSpec
from app.tools.tickets import get_ticket_repository

#: 假资产库：owner_id -> 资产。字段与 docs/06 的 query_cmdb 返回约定一致。
FAKE_ASSETS: dict[str, dict[str, Any]] = {
    "u_102": {
        "asset_id": "PC-20481",
        "owner_id": "u_102",
        "type": "laptop",
        "model": "ThinkPad T14",
        "status": "online",
        "ip": "10.20.31.44",
        "warranty_until": "2027-03-31",
    },
    "u_205": {
        "asset_id": "PC-20517",
        "owner_id": "u_205",
        "type": "laptop",
        "model": "MacBook Pro 14",
        "status": "online",
        "ip": "10.20.32.8",
        "warranty_until": "2028-01-15",
    },
}


async def query_cmdb(owner_id: str) -> dict[str, Any]:
    """按 owner 查设备信息（只读）。

    W1 是同步假数据；接真实 CMDB 时这里换成 `httpx.AsyncClient`，
    handler 必须响应 `CancelledError`（docs/06 §4）。
    """
    asset = FAKE_ASSETS.get(owner_id)
    if asset is None:
        # not_found 不重试，让 runtime 走「数据可能过期」的降级话术（docs/06 §6）
        raise ToolError(ToolErrorKind.NOT_FOUND, f"未找到 {owner_id} 名下资产")
    return dict(asset)


async def create_ticket(
    *,
    title: str,
    category: str,
    priority: str,
    asset_id: str | None = None,
    identity: Identity,
) -> dict[str, Any]:
    """创建工单（写操作，审批通过后才会执行）。

    requester 只取服务端注入的 identity：模型即使把 user_id 写进 args 也会在
    治理层被 RESERVED_ARGS 拒绝（R9）。
    """
    return await get_ticket_repository().create(
        title=title,
        category=category,
        priority=priority,
        requester=identity.user_id,
        asset_id=asset_id,
    )


async def query_tickets(
    *,
    status: str | None = None,
    limit: int = 5,
    identity: Identity,
) -> dict[str, Any]:
    """查当前用户名下的工单（只读）。

    requester 恒为服务端注入的 identity：模型无法查别人的工单（R9）。
    """
    rows = await get_ticket_repository().list_for_requester(
        identity.user_id, status=status, limit=limit
    )
    return {"tickets": rows, "count": len(rows)}


def build_registry() -> ToolRegistry:
    """注册 v1 工具。每个进程一份即可（工具无状态）。"""
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="query_cmdb",
            description="按 owner 查设备信息：型号、在线状态、IP、保修期",
            input_schema={
                "type": "object",
                "properties": {
                    "owner_id": {"type": "string", "description": "资产归属人 ID"},
                },
                "required": ["owner_id"],
                "additionalProperties": False,
            },
            handler=query_cmdb,
            is_write=False,
            timeout_ms=2000,
            roles=(),
        )
    )

    registry.register(
        ToolSpec(
            name="query_tickets",
            description="查当前用户名下的工单：单号、标题、优先级、状态、创建时间",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "按状态筛选",
                        "enum": ["open", "in_progress", "resolved", "closed"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回几条（1-20）",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "additionalProperties": False,
            },
            handler=query_tickets,
            is_write=False,
            timeout_ms=2000,
            roles=(),
            inject_identity=True,
        )
    )

    registry.register(
        ToolSpec(
            name="create_ticket",
            description="在 IT 服务台创建一张工单",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "工单标题"},
                    "category": {"type": "string", "description": "问题分类"},
                    "priority": {
                        "type": "string",
                        "description": "优先级",
                        "enum": ["P0", "P1", "P2", "P3"],
                    },
                    "asset_id": {"type": "string", "description": "关联资产号"},
                },
                "required": ["title", "category", "priority"],
                "additionalProperties": False,
            },
            handler=create_ticket,
            is_write=True,
            timeout_ms=3000,
            roles=(),
            inject_identity=True,
        )
    )

    return registry


@lru_cache
def default_registry() -> ToolRegistry:
    """进程内单例：注册成本低，但没必要每个 run 重建。"""
    return build_registry()
