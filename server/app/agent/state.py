"""Agent 状态定义。

字段与 docs/04-agent-design.md 的第 2 节保持一致。
这里用 TypedDict 而不是 dataclass：LangGraph 的 state 就是 dict，
用 TypedDict 可以让节点函数在 LangGraph 与手写调度器之间共用。
"""

from __future__ import annotations

from typing import Any, TypedDict


class Budget(TypedDict, total=False):
    remaining_cents: int
    used_steps: int


class AgentState(TypedDict, total=False):
    run_id: str
    user: dict[str, Any]  # {id, roles[], session_id}
    messages: list[dict[str, Any]]
    query: str
    intent: str
    incident_type: str  # hardware|network|software|account|other
    retrieved: list[dict[str, Any]]
    plan: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    step: int
    budget: Budget
    error: str | None


MAX_STEPS = 12
MAX_TOOL_CALLS = 6
MAX_REPLAN = 1
RUN_TIMEOUT_S = 120
BUDGET_CENTS = 50


def initial_state(*, run_id: str, user: dict[str, Any], query: str) -> AgentState:
    return AgentState(
        run_id=run_id,
        user=user,
        messages=[],
        query=query,
        intent="",
        incident_type="other",
        retrieved=[],
        plan=[],
        tool_results=[],
        pending_approval=None,
        step=0,
        budget=Budget(remaining_cents=BUDGET_CENTS, used_steps=0),
        error=None,
    )
