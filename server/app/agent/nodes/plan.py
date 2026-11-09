"""plan 节点：决定「查什么 / 做什么」。

W1 起是规则实现（docs/04 §3 的降级路径），W3 的 classify 已把意图拆出去，
这里只负责把意图变成工具计划。W4 接模型网关后再换 LLM + JSON Schema 约束，
节点签名不变。

两条边界：
- args 只能有业务参数，身份字段（user_id/role/tenant）一律不允许出现在计划里（R9）
- verify 判定失败的工具有记录在 `failed_tools`，重规划时不能再排一次（否则死循环）
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.nodes.classify import (
    INTENT_ASSET,
    INTENT_KNOWLEDGE,
    INTENT_TICKET,
    classify_incident,
)
from app.agent.state import AgentState


def plan_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：plan（以及旧版本需要的 intent/incident_type）。"""
    del deps
    query = state.get("query", "")
    incident = state.get("incident_type") or classify_incident(query)
    intent = state.get("intent") or INTENT_KNOWLEDGE
    blocked = set(state.get("failed_tools", []))

    plan: list[dict[str, Any]] = []
    if intent == INTENT_TICKET and "create_ticket" not in blocked:
        plan.append(
            {
                "tool": "create_ticket",
                "args": {
                    "title": query[:100],
                    "category": incident,
                    "priority": "P2",
                },
                "reason": "用户要求开单/报修，写操作必须人工审批",
            }
        )
    elif intent == INTENT_ASSET and "query_cmdb" not in blocked:
        plan.append(
            {
                "tool": "query_cmdb",
                "args": {"owner_id": state.get("user", {}).get("id", "")},
                "reason": "先确认名下资产状态，再给排查建议",
            }
        )

    return {"intent": intent, "incident_type": incident, "plan": plan}
