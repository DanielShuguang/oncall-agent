"""plan 节点：决定「查什么 / 做什么」（W4 D16：规则 + LLM）。

- `ONCALL_MOCK_MODE=true`：只走规则计划，无模型调用（无 key 演示）
- 真实模式：模型产出 `{calls:[{tool,args,reason}]}`，服务端逐条校验：
  - 工具必须已注册、参数必须过 `validate_args`（含 enum / 未知字段）
  - `query_cmdb.owner_id` 由服务端注入，模型写的值一律忽略（R9）
  - 模糊输入不允许计划写操作（R10）
  - 模型输出无法解析时重试 1 次，再失败退回规则计划

节点仍然是纯函数：不执行工具、不发事件；只返回 state 增量。
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.deps import AgentDeps
from app.agent.nodes.classify import (
    INTENT_ASSET,
    INTENT_KNOWLEDGE,
    INTENT_TICKET,
    classify_incident,
)
from app.agent.nodes.json_utils import extract_json_object
from app.agent.prompts import load_prompt
from app.agent.state import MAX_TOOL_CALLS, AgentState
from app.core.logging import get_logger
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    MeteringError,
    ModelUnavailable,
    ModelUsage,
    Purpose,
)
from app.tools.registry import Identity, ToolError, validate_args

log = get_logger(__name__)


def rule_plan(state: AgentState) -> list[dict[str, Any]]:
    """确定性规则计划：mock 模式与模型降级时的兜底。"""
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
    return plan


def _identity(state: AgentState) -> Identity:
    user = state.get("user", {})
    roles = frozenset(str(role) for role in user.get("roles", []))
    return Identity(user_id=str(user.get("id", "")), roles=roles)


def _evidence(state: AgentState) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for hit in state.get("retrieved", [])[:3]:
        evidence.append(
            {
                "title": str(hit.get("title", "")),
                "heading": str(hit.get("heading", "")),
                "snippet": str(hit.get("content", ""))[:240],
            }
        )
    return evidence


async def _messages(state: AgentState, deps: AgentDeps) -> list[ChatMessage]:
    identity = _identity(state)
    tools = [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
        }
        for spec in await deps.guard.effective_enabled(identity)
    ]
    payload = {
        "query": state.get("query", ""),
        "intent": state.get("intent", INTENT_KNOWLEDGE),
        "incident_type": state.get("incident_type", "other"),
        "evidence": _evidence(state),
        "tools": tools,
    }
    return [
        ChatMessage(role="system", content=load_prompt("plan")),
        ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]


async def _filter_plan(
    plan: list[dict[str, Any]], deps: AgentDeps, identity: Identity
) -> list[dict[str, Any]]:
    """规则计划也要遵守管理端覆盖：禁用的工具不能因为走了规则路径就复活。"""
    allowed: list[dict[str, Any]] = []
    for call in plan:
        spec = deps.guard.registry.try_get(str(call.get("tool", "")))
        if spec is None:
            continue
        effective = await deps.guard.effective_spec(spec)
        if not effective.enabled:
            continue
        if effective.roles and not identity.roles.intersection(effective.roles):
            continue
        allowed.append(call)
    return allowed


async def _calls_from_text(
    text: str, state: AgentState, deps: AgentDeps
) -> list[dict[str, Any]] | None:
    payload = extract_json_object(text)
    if payload is None:
        return None
    calls = payload.get("calls")
    if not isinstance(calls, list):
        return None

    user_id = str(state.get("user", {}).get("id", ""))
    incident = state.get("incident_type", "other")
    intent = state.get("intent", INTENT_KNOWLEDGE)
    blocked = set(state.get("failed_tools", []))
    identity = _identity(state)
    parsed: list[dict[str, Any]] = []

    for item in calls[:MAX_TOOL_CALLS]:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or tool in blocked:
            continue
        spec = deps.guard.registry.try_get(tool)
        if spec is None:
            continue
        spec = await deps.guard.effective_spec(spec)
        if not spec.enabled:
            continue
        if spec.roles and not identity.roles.intersection(spec.roles):
            continue
        if spec.is_write and intent != INTENT_TICKET:
            # 模糊输入不能凭模型一句话就升级成写操作
            continue

        raw_args = item.get("args")
        args: dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
        if tool == "query_cmdb":
            args["owner_id"] = user_id  # 身份字段由服务端注入（R9）
        if tool == "create_ticket":
            args.setdefault("title", str(state.get("query", ""))[:100])
            args.setdefault("category", incident)
            args.setdefault("priority", "P2")

        try:
            validate_args(spec.input_schema, args)
        except ToolError as exc:
            log.warning("plan_invalid_args", tool=tool, error=str(exc))
            continue
        reason = item.get("reason")
        parsed.append(
            {
                "tool": tool,
                "args": args,
                "reason": str(reason)[:200] if isinstance(reason, str) else "模型计划",
            }
        )

    if calls and not parsed:
        # 模型给了计划但全部不合法：不要执行空计划，退回规则更安全
        return None
    return parsed


async def plan_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：plan / plan_source / usage。"""
    intent = state.get("intent") or INTENT_KNOWLEDGE
    incident = state.get("incident_type") or classify_incident(state.get("query", ""))
    identity = _identity(state)
    fallback = await _filter_plan(rule_plan(state), deps, identity)

    if deps.gateway is None:
        return {
            "intent": intent,
            "incident_type": incident,
            "plan": fallback,
            "plan_source": "rule",
        }

    user = state.get("user", {})
    usage = ModelUsage()
    messages = await _messages(state, deps)
    completion = None
    try:
        completion = await deps.gateway.chat(
            messages,
            purpose=Purpose.PLAN,
            run_id=str(state.get("run_id", "")),
            step="plan",
            user_id=str(user.get("id", "")),
            spent_cents=ModelUsage.from_dict(state.get("usage")).cost_cents,
            max_tokens=400,
            json_mode=True,
            requested_model=deps.requested_model,
        )
    except BudgetExceeded:
        raise
    except (ModelUnavailable, MeteringError) as exc:
        log.warning("plan_model_fallback", run_id=state.get("run_id"), error=str(exc))
        return {
            "intent": intent,
            "incident_type": incident,
            "plan": fallback,
            "plan_source": "fallback",
            "usage": usage.as_dict(),
        }

    usage = usage.add(completion)
    calls = await _calls_from_text(completion.text, state, deps)
    if calls is None:
        # 解析失败重试一次（docs/04 §5）；仍然失败则退回规则计划
        retry_messages = [
            *messages,
            ChatMessage(role="assistant", content=completion.text[:500]),
            ChatMessage(role="user", content='只输出一个合法 JSON 对象 {"calls": [...]}'),
        ]
        try:
            completion = await deps.gateway.chat(
                retry_messages,
                purpose=Purpose.PLAN,
                run_id=str(state.get("run_id", "")),
                step="plan",
                user_id=str(user.get("id", "")),
                spent_cents=ModelUsage.from_dict(state.get("usage")).cost_cents + usage.cost_cents,
                max_tokens=400,
                json_mode=True,
                requested_model=deps.requested_model,
            )
        except BudgetExceeded:
            raise
        except (ModelUnavailable, MeteringError) as exc:
            log.warning("plan_retry_failed", run_id=state.get("run_id"), error=str(exc))
            calls = None
        else:
            usage = usage.add(completion)
            calls = await _calls_from_text(completion.text, state, deps)

    if calls is None:
        return {
            "intent": intent,
            "incident_type": incident,
            "plan": fallback,
            "plan_source": "fallback",
            "usage": usage.as_dict(),
        }
    return {
        "intent": intent,
        "incident_type": incident,
        "plan": calls,
        "plan_source": "llm",
        "usage": usage.as_dict(),
    }
