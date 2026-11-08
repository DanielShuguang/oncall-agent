"""LangGraph 状态机（W3 D11 起实现）。

设计见 docs/04-agent-design.md。当前为占位：import 时才引入 langgraph，
保证 `uv sync`（最小依赖）也能启动服务。

实现要点（照做即可）：
1. 节点函数放 `nodes/`，签名统一为 `(state, deps) -> dict`（返回 state 的增量）
2. 节点不发事件；事件由 runtime 统一发出（避免节点里到处 yield）
3. `checkpointer` 用 Postgres saver，配合事件表实现断点续跑
4. 手写调度器 `simple_runner.py` 与该图共用节点，互为 fallback
"""

from __future__ import annotations

from typing import Any

from app.agent.state import AgentState


def build_graph(deps: Any = None) -> Any:
    """构建并编译 Agent 图。

    TODO(W3 D11): 实现 8 节点：
        intake -> classify -> retrieve -> plan -> act -> verify -> approve -> finalize
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - 仅在未安装 extras 时触发
        raise RuntimeError(
            "未安装 agent 依赖，请执行：uv sync --extra agent"
        ) from exc

    graph = StateGraph(AgentState)

    # 占位节点：保证图可编译，便于前端联调
    async def passthrough(state: AgentState) -> dict[str, Any]:
        return {"step": state.get("step", 0) + 1}

    graph.add_node("intake", passthrough)
    graph.set_entry_point("intake")
    graph.add_edge("intake", END)

    return graph.compile()
