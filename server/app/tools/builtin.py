"""v1 内置工具的实现与注册。

治理逻辑全部在 `registry.py`（R3），这里只负责「工具做什么」：

- `query_cmdb`：查当前用户名下资产。数据来自 `assets` 表（ADR-0034），
  身份由 ToolGuard 注入；换真实 CMDB 时只替换 `tools/assets.py` 的仓储，
  `input_schema` / 超时 / 角色约束与治理链路不变（docs/06 §8.2）。
- `create_ticket`：写操作，**永远不在这里判断能不能执行** —— 由 `ToolGuard` 挂起
  等审批（R10），审批通过后 runtime 用 `allow_write=True` 才走到 handler。
  requester 由 ToolGuard 注入服务端身份，不来自模型参数（R9）。

`query_tickets` 只查本人，同样依赖注入的 identity（ADR-0029）。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.tools.assets import get_asset_repository
from app.tools.registry import Identity, ToolRegistry, ToolSpec
from app.tools.tickets import get_ticket_repository

# 校验器不执行 schema 的 pattern（docs/06），这里再兜一层：
# 格式不对按「没查到」处理，避免把任意长字符串带进仓储查询。
_TICKET_ID_RE = re.compile(r"TCK-[0-9A-F]{8}")


async def query_cmdb(*, asset_id: str | None = None, identity: Identity) -> dict[str, Any]:
    """查当前用户名下资产（只读）。

    模型可以按资产号缩小范围，但不能指定 owner：`owner_id` 不在 schema 里，
    仓储也只按注入的 `identity.user_id` 过滤（R9）。空结果是合法结果，
    由 finalize 说明「没查到资产」，不是工具失败。
    """
    rows = await get_asset_repository().list_for_owner(
        identity.user_id, asset_id=asset_id, limit=20
    )
    return {"assets": rows, "count": len(rows)}


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
    ticket_id: str | None = None,
    status: str | None = None,
    limit: int = 5,
    identity: Identity,
) -> dict[str, Any]:
    """查当前用户名下的工单（只读）。

    requester 恒为服务端注入的 identity：模型无法查别人的工单（R9）。
    给了单号就只查这一张（按本人过滤，别人的单等同不存在），否则列最近 N 张。
    """
    repository = get_ticket_repository()
    if ticket_id is not None:
        normalized = ticket_id.strip().upper()
        if _TICKET_ID_RE.fullmatch(normalized) is None:
            return {"ticket": None}
        ticket = await repository.get_for_requester(identity.user_id, normalized)
        return {"ticket": ticket}
    rows = await repository.list_for_requester(identity.user_id, status=status, limit=limit)
    return {"tickets": rows, "count": len(rows)}


def build_registry() -> ToolRegistry:
    """注册 v1 工具。每个进程一份即可（工具无状态）。"""
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="query_cmdb",
            description="查当前用户名下资产：型号、在线状态、IP、保修期",
            input_schema={
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 32,
                        "description": "资产号，可缩小到某一台",
                    },
                },
                "additionalProperties": False,
            },
            handler=query_cmdb,
            is_write=False,
            timeout_ms=2000,
            roles=(),
            inject_identity=True,
        )
    )

    registry.register(
        ToolSpec(
            name="query_tickets",
            description=(
                "查当前用户名下的工单：单号、标题、优先级、状态、创建时间；"
                "给 ticket_id 可查这一张的详情（描述、处理人、解决时间）"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "pattern": "^[Tt][Cc][Kk]-[0-9A-Fa-f]{8}$",
                        "description": "工单号（形如 TCK-1A2B3C4D）；给了就只查这一张",
                    },
                    "status": {
                        "type": "string",
                        "description": "按状态筛选（只在列表模式生效）",
                        "enum": ["open", "in_progress", "resolved", "closed"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回几条（1-20，只在列表模式生效）",
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
