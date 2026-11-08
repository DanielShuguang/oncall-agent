"""Agent 运行时（W1 D5）。

把「规则节点 + 工具治理 + 事件流」串成一条真实的 run：

    run.started
      → intake   step.started / step.completed（规则：规范化输入）
      → plan     step.started / step.completed（规则：产出工具计划）
      → act      tool.call → ToolGuard 执行 → tool.result（写操作 → approval.required）
      → finalize message.delta… → message.completed → run.completed

三条硬约束：
- 节点是纯函数 `(state, deps) -> dict`，**不发事件**；事件统一由这里发（R5）
- 工具只能经 `ToolGuard.execute()` 执行，runtime 不做权限判断（R3）
- 事件先由调用方落库、再推送（R2）；runtime 只负责「产出事件」

W1 的 plan/finalize 都是规则实现；W2 接 RAG、W3 把 plan 换成 LLM 时只替换节点。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, cast

from app.agent.deps import AgentDeps
from app.agent.nodes.finalize import finalize_node
from app.agent.nodes.intake import intake_node
from app.agent.nodes.plan import plan_node
from app.agent.state import (
    MAX_STEPS,
    MAX_TOOL_CALLS,
    AgentState,
    initial_state,
)
from app.core.logging import get_logger
from app.schemas.event import EventType
from app.tools.builtin import default_registry
from app.tools.registry import Decision, Identity, ToolGuard

log = get_logger(__name__)

#: (事件类型, payload)。runtime 只产出事件，落库/推送由 api 层负责。
Event = tuple[EventType, dict[str, Any]]

CHUNK_SIZE = 24
CHUNK_DELAY_S = 0.005
APPROVAL_TTL_MIN = 10


def build_deps(model: str = "") -> AgentDeps:
    return AgentDeps(guard=ToolGuard(default_registry()), model=model)


async def stream(
    *,
    run_id: str,
    identity: Identity,
    query: str,
    model: str,
    max_steps: int = MAX_STEPS,
    deps: AgentDeps | None = None,
) -> AsyncIterator[Event]:
    """执行一次 run 并产出事件。

    调用方（`api/chat.py`）负责：建 run、append 事件、推 SSE、断开时标 interrupted。
    这里不碰存储，也不吞掉 `CancelledError`（客户端断开的信号要往上抛）。
    """
    resolved = deps or build_deps(model)
    state = initial_state(
        run_id=run_id,
        user={"id": identity.user_id, "roles": sorted(identity.roles)},
        query=query,
    )
    yield (
        EventType.RUN_STARTED,
        {
            "run_id": run_id,
            "model": model,
            "max_steps": max_steps,
        },
    )

    started_at = perf_counter()
    step = 0
    tool_calls = 0

    try:
        # ---------- intake ----------
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        yield EventType.STEP_STARTED, {"step": step, "node": "intake", "title": "理解问题"}
        node_started = perf_counter()
        state = _merge(state, intake_node(state, resolved))
        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "intake",
                "duration_ms": _ms(node_started),
                "summary": "输入已规范化",
            },
        )

        # ---------- plan ----------
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        yield EventType.STEP_STARTED, {"step": step, "node": "plan", "title": "制定处理计划"}
        node_started = perf_counter()
        state = _merge(state, plan_node(state, resolved))
        plan = state.get("plan", [])
        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "plan",
                "duration_ms": _ms(node_started),
                "summary": (
                    f"类型 {state.get('intent', 'other')}，计划 {len(plan)} 个工具调用"
                    if plan
                    else f"类型 {state.get('intent', 'other')}，无需调用工具"
                ),
            },
        )

        # ---------- act（工具执行必须过治理层）----------
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        yield EventType.STEP_STARTED, {"step": step, "node": "act", "title": "调用工具"}
        node_started = perf_counter()

        for call in plan:
            tool = str(call.get("tool", ""))
            raw_args = call.get("args")
            args: dict[str, Any] = dict(raw_args) if isinstance(raw_args, Mapping) else {}

            if tool_calls >= MAX_TOOL_CALLS:
                yield _failed("TOOL_LIMIT", f"工具调用超过上限 {MAX_TOOL_CALLS}", step)
                return
            tool_calls += 1
            call_id = f"call_{tool_calls}"
            spec = resolved.guard.registry.try_get(tool)

            yield (
                EventType.TOOL_CALL,
                {
                    "call_id": call_id,
                    "tool": tool,
                    "args": args,
                    "write": bool(spec.is_write) if spec is not None else False,
                },
            )

            result = await resolved.guard.execute(tool, args, identity, call_id=call_id)
            yield EventType.TOOL_RESULT, result.to_payload()

            if result.decision is Decision.REQUIRES_APPROVAL:
                yield (
                    EventType.STEP_COMPLETED,
                    {
                        "step": step,
                        "node": "act",
                        "duration_ms": _ms(node_started),
                        "summary": "写操作已挂起，等待审批",
                    },
                )
                yield EventType.APPROVAL_REQUIRED, _approval_payload(tool, args, result.approval)
                return

            state["tool_results"].append(result.to_payload())

        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "act",
                "duration_ms": _ms(node_started),
                "summary": f"调用 {tool_calls} 个工具" if tool_calls else "无需调用工具",
            },
        )

        # ---------- finalize ----------
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        yield EventType.STEP_STARTED, {"step": step, "node": "finalize", "title": "组织回答"}
        node_started = perf_counter()
        state = _merge(state, finalize_node(state, resolved))
        answer = _last_message_text(state)

        for index in range(0, len(answer), CHUNK_SIZE):
            yield EventType.MESSAGE_DELTA, {"text": answer[index : index + CHUNK_SIZE]}
            await asyncio.sleep(CHUNK_DELAY_S)

        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "finalize",
                "duration_ms": _ms(node_started),
                "summary": "回答已生成",
            },
        )
        yield EventType.MESSAGE_COMPLETED, {"text": answer, "citations": []}
        yield (
            EventType.RUN_COMPLETED,
            {
                "status": "completed",
                "steps": step,
                "token_in": 0,
                "token_out": 0,
                "cost_cents": 0,
                "duration_ms": _ms(started_at),
            },
        )

    except Exception:  # 运行期失败必须变成事件，不能把连接打成 500
        log.exception("agent_run_failed", run_id=run_id, step=step)
        yield _failed("INTERNAL_ERROR", "运行时内部错误", step)


def _merge(state: AgentState, delta: Mapping[str, Any] | None) -> AgentState:
    return cast(AgentState, {**state, **(delta or {})})


def _last_message_text(state: AgentState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return ""
    return str(messages[-1].get("content", ""))


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _failed(error_code: str, message: str, at_step: int) -> Event:
    return (
        EventType.RUN_FAILED,
        {"error_code": error_code, "message": message, "at_step": at_step},
    )


def _approval_payload(
    tool: str,
    args: Mapping[str, Any],
    approval: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expires = datetime.now(UTC) + timedelta(minutes=APPROVAL_TTL_MIN)
    return {
        "approval_id": f"apr_{uuid.uuid4().hex[:12]}",
        "tool": tool,
        "args": dict(args),
        "risk_level": (approval or {}).get("risk_level", "medium"),
        "reason": (
            "将在工单系统创建一条记录，影响：IT 服务台派单"
            if tool == "create_ticket"
            else f"将执行写操作 {tool}，需要人工确认"
        ),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
