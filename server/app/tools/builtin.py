"""v1 内置工具的实现与注册（W1 D5 用内存假数据）。

治理逻辑全部在 `registry.py`（R3），这里只负责「工具做什么」：

- `query_cmdb`：查用户名下资产。W1 用内存假数据，接真实 CMDB 时只替换 handler，
  `input_schema` / 超时 / 角色约束不变，治理链路不用动（docs/06 §8.2）。
- `create_ticket`：写操作，**永远不在这里判断能不能执行** —— 由 `ToolGuard` 挂起
  等审批（R10），审批通过后 W3 D14 才会走到 handler。

⚠️ 本模块的读工具是假数据，不是从 CMDB 拉的，演示时不要当成真实资产。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.tools.registry import ToolError, ToolErrorKind, ToolRegistry, ToolSpec

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
) -> dict[str, Any]:
    """创建工单（写操作）。

    正常链路走不到这里：`ToolGuard` 在 `is_write` 时直接返回
    `REQUIRES_APPROVAL`。W3 D14 接通审批后由 runtime 用 `allow_write=True` 执行。
    """
    raise ToolError(
        ToolErrorKind.INTERNAL,
        "写操作尚未接入（W3 D14 审批通过后执行）",
        idempotent_safe=False,
    )


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
            },
            handler=query_cmdb,
            is_write=False,
            timeout_ms=2000,
            roles=(),
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
                    "priority": {"type": "string", "description": "优先级，如 P1/P2/P3"},
                    "asset_id": {"type": "string", "description": "关联资产号"},
                },
                "required": ["title", "category", "priority"],
            },
            handler=create_ticket,
            is_write=True,
            timeout_ms=3000,
            roles=(),
        )
    )

    return registry


@lru_cache
def default_registry() -> ToolRegistry:
    """进程内单例：注册成本低，但没必要每个 run 重建。"""
    return build_registry()
