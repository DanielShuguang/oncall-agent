"""运行时依赖（节点与 runtime 共享）。

节点只拿到 `AgentDeps`，不直接碰 HTTP / 数据库 / 事件发送：
- 模型调用留到 W3 D13 的 plan 节点（gateway 在 W4 接）
- 工具执行统一走 `guard`，节点自己不调 handler
"""

from __future__ import annotations

from dataclasses import dataclass

from app.tools.registry import ToolGuard


@dataclass(frozen=True, slots=True)
class AgentDeps:
    guard: ToolGuard
