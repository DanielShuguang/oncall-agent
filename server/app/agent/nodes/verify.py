"""verify 节点：结果校验（规则）。

判定口径（docs/04 §3）：单个工具失败不中断 run，但也不能假装成功。
- `timeout` / `error` 且错误类型属于可恢复（timeout/network/internal）→ 触发一次重规划
- `not_found` / `permission` / `invalid_args` → 重规划也不会变好，直接降级继续
- 已经重规划过一次 → 不再重试，把失败留给 finalize 的降级话术

`failed_tools` 记录已经判过失败的工具，plan 节点据此避免重复排同一个工具。
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import MAX_REPLAN, AgentState

#: 重规划有意义的错误类型；参数错误/权限/不存在换一次计划也不会变好
REPLANNABLE_ERROR_KINDS = frozenset({"timeout", "network", "internal"})


def needs_replan(result: dict[str, Any]) -> bool:
    status = result.get("status")
    if status == "timeout":
        return True
    if status != "error":
        return False
    return str(result.get("error_kind", "")) in REPLANNABLE_ERROR_KINDS


def verify_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：verify_ok / replan_count / failed_tools。"""
    del deps
    handled = set(state.get("failed_tools", []))
    new_failures = {
        str(result.get("tool", ""))
        for result in state.get("tool_results", [])
        if needs_replan(result) and str(result.get("tool", "")) not in handled
    }
    new_failures.discard("")

    if not new_failures:
        return {"verify_ok": True}

    merged = sorted(handled | new_failures)
    replanned = int(state.get("replan_count", 0))
    if replanned >= MAX_REPLAN:
        # 重规划次数用尽：降级继续，由 finalize 输出「数据可能过期」类话术
        return {"verify_ok": True, "failed_tools": merged}

    return {
        "verify_ok": False,
        "replan_count": replanned + 1,
        "failed_tools": merged,
    }
