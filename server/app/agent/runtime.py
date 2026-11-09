"""Agent 运行时（W1 D5 → W3 D11-D15）。

把「8 节点状态机 + 工具治理 + 人工审批 + 事件流」串成一条真实的 run：

    run.started
      → intake   规则：规范化输入
      → classify 规则：意图识别（ticket_create / asset_check / knowledge）
      → retrieve 规则：RAG 混合检索 + 阈值
      → plan     规则：产出工具计划（重规划时跳过已失败工具）
      → act      规则：ToolGuard 执行；写操作 → approval.required，run 挂起
      → verify   规则：结果校验；可重规划一次
      → finalize message.delta… → message.completed → run.completed

审批通过后由 `resume()` 从快照恢复：approve → act（allow_write=True）→ verify → finalize。

三条硬约束：
- 节点是纯函数 `(state, deps) -> dict`，**不发事件**；事件统一由这里发（R5）
- 工具只能经 `ToolGuard.execute()` 执行，runtime 不做权限判断（R3）
- 事件先由调用方落库、再推送（R2）；runtime 只负责「产出事件」

`act` 是唯一需要逐次发 tool.call 的节点，所以执行循环留在这里：
它的「计划」由 plan 节点产出，「能不能执行」由 ToolGuard 决定，runtime 只做调度。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, cast

from app.agent.deps import AgentDeps
from app.agent.graph import NODE_TITLES, next_node
from app.agent.nodes.classify import classify_node
from app.agent.nodes.finalize import finalize_node
from app.agent.nodes.intake import intake_node
from app.agent.nodes.plan import plan_node
from app.agent.nodes.retrieve import retrieve_node
from app.agent.nodes.verify import verify_node
from app.agent.state import (
    MAX_STEPS,
    MAX_TOOL_CALLS,
    RUN_TIMEOUT_S,
    AgentState,
    initial_state,
)
from app.approvals.types import ApprovalRecord, ApprovalRecorder, ApprovalRequestInfo
from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.service import get_knowledge_base
from app.schemas.event import EventType
from app.tools.builtin import default_registry
from app.tools.registry import Decision, Identity, ToolGuard

log = get_logger(__name__)

#: (事件类型, payload)。runtime 只产出事件，落库/推送由 api 层负责。
Event = tuple[EventType, dict[str, Any]]

CHUNK_SIZE = 24
CHUNK_DELAY_S = 0.005
APPROVAL_TTL_MIN = 10


def build_deps(*, approvals: ApprovalRecorder | None = None) -> AgentDeps:
    settings = get_settings()
    return AgentDeps(
        guard=ToolGuard(default_registry()),
        retriever=get_knowledge_base(),
        top_k=settings.rag_top_k,
        approvals=approvals,
    )


async def _run_node(name: str, state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    if name == "intake":
        return intake_node(state, deps)
    if name == "classify":
        return classify_node(state, deps)
    if name == "retrieve":
        return await retrieve_node(state, deps)
    if name == "plan":
        return plan_node(state, deps)
    if name == "verify":
        return verify_node(state, deps)
    raise ValueError(f"未知节点: {name}")


def _summary(node: str, state: AgentState) -> str:
    if node == "intake":
        return "输入已规范化"
    if node == "classify":
        intent = state.get("intent", "knowledge")
        incident = state.get("incident_type", "other")
        return f"意图 {intent}，类型 {incident}"
    if node == "retrieve":
        hits = len(state.get("retrieved", []))
        return f"命中 {hits} 条资料" if hits else "未命中，走兜底话术"
    if node == "plan":
        plan = state.get("plan", [])
        if plan:
            return f"计划 {len(plan)} 个工具调用"
        return "无需调用工具"
    if node == "verify":
        if state.get("verify_ok", True):
            return "校验通过"
        return f"发现工具失败，准备重规划（第 {state.get('replan_count', 1)} 次）"
    if node == "act":
        return "调用完成"
    return ""


async def stream(
    *,
    run_id: str,
    identity: Identity,
    query: str,
    model: str,
    max_steps: int = MAX_STEPS,
    timeout_s: float = RUN_TIMEOUT_S,
    deps: AgentDeps | None = None,
    session_id: str | None = None,
) -> AsyncIterator[Event]:
    """执行一次 run 并产出事件。

    调用方（`api/chat.py`）负责：建 run、append 事件、推 SSE、断开时标 interrupted。
    这里不碰存储，也不吞掉 `CancelledError`（客户端断开的信号要往上抛）。
    总时长在节点/工具边界检查（不做硬中断：工具自身有超时，见 docs/06 §4）。
    """
    resolved = deps or build_deps()
    user = {"id": identity.user_id, "roles": sorted(identity.roles)}
    if session_id:
        user["session_id"] = session_id
    state = initial_state(run_id=run_id, user=user, query=query)
    yield (
        EventType.RUN_STARTED,
        {
            "run_id": run_id,
            "model": model,
            "max_steps": max_steps,
        },
    )

    started_at = perf_counter()
    deadline = started_at + timeout_s
    step = 0
    tool_calls = 0
    node: str | None = "intake"

    try:
        while node is not None:
            expired = _timeout_event(deadline, timeout_s, step)
            if expired is not None:
                yield expired
                return
            step += 1
            if step > max_steps:
                yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
                return

            state["step"] = step
            state["node"] = node
            yield (
                EventType.STEP_STARTED,
                {"step": step, "node": node, "title": NODE_TITLES[node]},
            )
            node_started = perf_counter()

            if node == "finalize":
                state = _merge(state, finalize_node(state, resolved))
                async for event in _finalize_events(
                    state, started_at=started_at, step=step, node_started=node_started
                ):
                    yield event
                return

            if node == "act":
                for call in state.get("plan", []):
                    expired = _timeout_event(deadline, timeout_s, step)
                    if expired is not None:
                        yield expired
                        return

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

                    # 会话级授权：审批人已同意本会话同类工具不再询问（docs/06 §7）
                    if (
                        result.decision is Decision.REQUIRES_APPROVAL
                        and resolved.approvals is not None
                        and await resolved.approvals.is_granted(
                            session_id=session_id, tool_name=tool
                        )
                    ):
                        result = await resolved.guard.execute(
                            tool, args, identity, call_id=call_id, allow_write=True
                        )

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
                        info = None
                        if resolved.approvals is not None:
                            info = await resolved.approvals.request(
                                run_id=run_id,
                                call_id=call_id,
                                session_id=session_id,
                                tool_name=tool,
                                args=args,
                                risk_level=str((result.approval or {}).get("risk_level", "medium")),
                                state=_snapshot(state),
                                requested_by=identity.user_id,
                            )
                        yield (
                            EventType.APPROVAL_REQUIRED,
                            _approval_payload(tool, args, result.approval, info),
                        )
                        return

                    state.setdefault("tool_results", []).append(result.to_payload())

                yield (
                    EventType.STEP_COMPLETED,
                    {
                        "step": step,
                        "node": "act",
                        "duration_ms": _ms(node_started),
                        "summary": f"调用 {tool_calls} 个工具" if tool_calls else "无需调用工具",
                    },
                )
                node = next_node("act")
                continue

            state = _merge(state, await _run_node(node, state, resolved))
            yield (
                EventType.STEP_COMPLETED,
                {
                    "step": step,
                    "node": node,
                    "duration_ms": _ms(node_started),
                    "summary": _summary(node, state),
                },
            )
            node = next_node(
                node,
                verify_ok=state.get("verify_ok", True),
                replan_count=state.get("replan_count", 0),
            )

    except Exception:  # 运行期失败必须变成事件，不能把连接打成 500
        log.exception("agent_run_failed", run_id=run_id, step=step)
        yield _failed("INTERNAL_ERROR", "运行时内部错误", step)


async def resume(
    *,
    approval: ApprovalRecord,
    deps: AgentDeps | None = None,
    max_steps: int = MAX_STEPS,
    timeout_s: float = RUN_TIMEOUT_S,
) -> AsyncIterator[Event]:
    """审批通过后从快照恢复：approve → act(allow_write) → verify → finalize。

    只执行挂起时那一个工具调用；不重跑 intake/retrieve/plan —— 审批人看到的是
    当时的参数与证据，执行也必须是同一份。
    """
    resolved = deps or build_deps()
    state = cast(AgentState, dict(approval.state))
    state["run_id"] = approval.run_id
    state["node"] = "approve"
    roles = frozenset(str(role) for role in state.get("user", {}).get("roles", []))
    identity = Identity(user_id=approval.requested_by, roles=roles)
    step = int(state.get("step", 0) or 0)

    started_at = perf_counter()
    deadline = started_at + timeout_s

    try:
        expired = _timeout_event(deadline, timeout_s, step)
        if expired is not None:
            yield expired
            return
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        state["step"] = step
        state["node"] = "approve"
        yield (
            EventType.STEP_STARTED,
            {"step": step, "node": "approve", "title": NODE_TITLES["approve"]},
        )
        approve_duration = _ms(started_at)
        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "approve",
                "duration_ms": approve_duration,
                "summary": f"已由 {approval.resolved_by or '审批人'} 批准",
            },
        )

        # ---- act：只执行挂起的那一个调用 ----
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        state["step"] = step
        state["node"] = "act"
        yield EventType.STEP_STARTED, {"step": step, "node": "act", "title": NODE_TITLES["act"]}
        node_started = perf_counter()
        args = dict(approval.args)
        yield (
            EventType.TOOL_CALL,
            {
                "call_id": approval.call_id,
                "tool": approval.tool_name,
                "args": args,
                "write": True,
            },
        )
        result = await resolved.guard.execute(
            approval.tool_name,
            args,
            identity,
            call_id=approval.call_id,
            allow_write=True,
        )
        yield EventType.TOOL_RESULT, result.to_payload()

        if result.status.value != "ok":
            yield (
                EventType.STEP_COMPLETED,
                {
                    "step": step,
                    "node": "act",
                    "duration_ms": _ms(node_started),
                    "summary": "写操作执行失败",
                },
            )
            yield _failed(
                "TOOL_ERROR",
                result.error or "写操作执行失败，请手动提交工单",
                step,
            )
            return

        state.setdefault("tool_results", []).append(result.to_payload())
        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "act",
                "duration_ms": _ms(node_started),
                "summary": "写操作已执行",
            },
        )

        # ---- verify ----
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        state["step"] = step
        state["node"] = "verify"
        yield (
            EventType.STEP_STARTED,
            {
                "step": step,
                "node": "verify",
                "title": NODE_TITLES["verify"],
            },
        )
        node_started = perf_counter()
        state = _merge(state, verify_node(state, resolved))
        yield (
            EventType.STEP_COMPLETED,
            {
                "step": step,
                "node": "verify",
                "duration_ms": _ms(node_started),
                "summary": _summary("verify", state),
            },
        )

        # ---- finalize ----
        step += 1
        if step > max_steps:
            yield _failed("STEP_LIMIT", f"超过最大步数 {max_steps}", step)
            return
        state["step"] = step
        state["node"] = "finalize"
        yield (
            EventType.STEP_STARTED,
            {
                "step": step,
                "node": "finalize",
                "title": NODE_TITLES["finalize"],
            },
        )
        node_started = perf_counter()
        state = _merge(state, finalize_node(state, resolved))
        async for event in _finalize_events(
            state, started_at=started_at, step=step, node_started=node_started
        ):
            yield event

    except Exception:
        log.exception("agent_resume_failed", run_id=approval.run_id, step=step)
        yield _failed("INTERNAL_ERROR", "审批后恢复执行失败", step)


async def _finalize_events(
    state: AgentState, *, started_at: float, step: int, node_started: float
) -> AsyncIterator[Event]:
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
    yield (
        EventType.MESSAGE_COMPLETED,
        {
            "text": answer,
            "citations": state.get("citations", []),
        },
    )
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


def _snapshot(state: AgentState) -> dict[str, Any]:
    """挂起时冻结执行上下文；审批通过后按这一份恢复（docs/06 §7 参数快照）。"""
    keys = (
        "run_id",
        "user",
        "query",
        "intent",
        "incident_type",
        "retrieved",
        "citations",
        "plan",
        "tool_results",
        "step",
        "node",
        "verify_ok",
        "replan_count",
        "failed_tools",
    )
    return {key: state.get(key) for key in keys}


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


def _timeout_event(deadline: float, timeout_s: float, step: int) -> Event | None:
    if perf_counter() < deadline:
        return None
    return _failed("TIMEOUT", f"超过单 run 时长上限 {timeout_s:g}s", step)


def _approval_payload(
    tool: str,
    args: Mapping[str, Any],
    approval: Mapping[str, Any] | None,
    info: ApprovalRequestInfo | None = None,
) -> dict[str, Any]:
    ttl = get_settings().approval_ttl_min
    if info is not None:
        approval_id = info.approval_id
        expires_at = info.expires_at
    else:
        # runtime 单测没有审批存储时的兜底：仍给出可展示的 id/过期时间
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        expires_at = datetime.now(UTC) + timedelta(minutes=ttl)
    return {
        "approval_id": str(approval_id),
        "tool": tool,
        "args": dict(args),
        "risk_level": (approval or {}).get("risk_level", "medium"),
        "reason": (
            "将在工单系统创建一条记录，影响：IT 服务台派单"
            if tool == "create_ticket"
            else f"将执行写操作 {tool}，需要人工确认"
        ),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# 供测试断言：状态快照里不能丢的关键字段
SNAPSHOT_KEYS = (
    "run_id",
    "user",
    "query",
    "retrieved",
    "plan",
    "tool_results",
    "step",
)


__all__ = ["Event", "build_deps", "resume", "stream"]
