"""8 节点图（W3 D11/D13）：转移表、意图识别、verify 重规划。"""

from __future__ import annotations

from dataclasses import replace

from app.agent.deps import AgentDeps
from app.agent.graph import NODES, next_node
from app.agent.nodes.classify import (
    classify_incident,
    classify_intent,
    classify_node,
    needs_model,
    wants_ticket_status,
)
from app.agent.nodes.finalize import compose_answer
from app.agent.nodes.plan import plan_node, rule_plan
from app.agent.nodes.verify import verify_node
from app.agent.runtime import stream
from app.agent.state import initial_state
from app.tools.builtin import default_registry
from app.tools.registry import (
    Identity,
    ToolError,
    ToolErrorKind,
    ToolGuard,
    ToolRegistry,
    ToolSpec,
)

EMPLOYEE = Identity(user_id="u_102", roles=frozenset({"employee"}))


def test_graph_has_eight_nodes_in_documented_order() -> None:
    assert NODES == (
        "intake",
        "classify",
        "retrieve",
        "plan",
        "act",
        "verify",
        "approve",
        "finalize",
    )


def test_next_node_paths() -> None:
    assert next_node("intake") == "classify"
    assert next_node("classify") == "retrieve"
    assert next_node("retrieve") == "plan"
    assert next_node("plan") == "act"
    assert next_node("act") == "verify"
    assert next_node("verify", verify_ok=True) == "finalize"
    assert next_node("verify", verify_ok=False, replan_count=1) == "plan"
    # 防御：重规划次数已用完就继续 finalize，不能无限循环
    assert next_node("verify", verify_ok=False, replan_count=2) == "finalize"
    assert next_node("approve") == "act"
    assert next_node("finalize") is None


def test_classify_splits_intent_from_incident() -> None:
    assert classify_incident("打印机蓝屏了") == "hardware"
    assert classify_incident("VPN 连不上") == "network"
    assert classify_incident("想装个软件") == "software"

    assert classify_intent("帮我开一张报修工单", "hardware") == "ticket_create"
    assert classify_intent("打印机离线了", "hardware") == "asset_check"
    assert classify_intent("VPN 连不上怎么办", "network") == "knowledge"


def test_classify_policy_question_is_not_asset_check() -> None:
    # 出现设备名但在问保修/时长 → 知识问答，不能去查资产
    assert classify_intent("公司电脑保修几年", "hardware") == "knowledge"
    assert classify_intent("笔记本电池保修多久", "hardware") == "knowledge"
    # 明确报修仍然是资产查询
    assert classify_intent("打印机卡纸了", "hardware") == "asset_check"


def test_classify_personal_warranty_stays_asset_check() -> None:
    # 多跳保修问题带个人指代/故障症状，必须查资产，不能被政策守卫误伤
    assert classify_intent("我的电脑保修到什么时候", "hardware") == "asset_check"
    assert classify_intent("笔记本电池不耐用，保修多久", "hardware") == "asset_check"
    assert classify_intent("显示器接扩展坞闪烁，算保修范围吗", "hardware") == "asset_check"


def test_classify_incident_keyword_coverage() -> None:
    assert classify_incident("台式机风扇很响") == "hardware"
    assert classify_incident("公司统一代理地址是多少") == "network"
    assert classify_incident("我的设备连不上网") == "network"
    # software 优先于 account：「软件安装权限」主领域是软件
    assert classify_incident("帮我申请软件安装权限") == "software"
    # 平板是资产，但症状仍然是网络
    assert classify_intent("平板连不上 WiFi", classify_incident("平板连不上 WiFi")) == (
        "asset_check"
    )


async def test_classify_node_returns_delta() -> None:
    state = initial_state(
        run_id="r1", user={"id": "u_102", "roles": ["employee"]}, query=" 打印机 离线 "
    )
    # intake 之后 query 才是规范化后的；这里直接验证节点产出的意图字段
    delta = await classify_node(
        {**state, "query": "打印机离线"}, AgentDeps(guard=ToolGuard(default_registry()))
    )
    assert delta["intent"] == "asset_check"
    assert delta["incident_type"] == "hardware"
    assert delta["classified_by"] == "rule"
    assert delta["usage"] == {"token_in": 0, "token_out": 0, "cost_cents": 0, "calls": 0}


async def test_verify_reports_failure_once_and_plan_skips_it() -> None:
    deps = AgentDeps(guard=ToolGuard(default_registry()))
    state = initial_state(run_id="r1", user={"id": "u_102"}, query="打印机离线")
    state["intent"] = "asset_check"
    state["tool_results"] = [{"tool": "query_cmdb", "status": "timeout", "error_kind": "timeout"}]

    first = verify_node(state, deps)
    assert first["verify_ok"] is False
    assert first["replan_count"] == 1
    assert first["failed_tools"] == ["query_cmdb"]

    replanned = {**state, **first}
    assert (await plan_node(replanned, deps))["plan"] == []
    assert verify_node(replanned, deps)["verify_ok"] is True


def test_verify_ignores_terminal_errors() -> None:
    deps = AgentDeps(guard=ToolGuard(default_registry()))
    state = initial_state(run_id="r1", user={"id": "u_none"}, query="打印机离线")
    state["tool_results"] = [{"tool": "query_cmdb", "status": "error", "error_kind": "not_found"}]
    # 资产不存在重规划也没用，直接降级
    assert verify_node(state, deps) == {"verify_ok": True}


async def _run_with_failing_cmdb() -> list[tuple[object, dict[str, object]]]:
    async def failing(**_: object) -> dict[str, object]:
        raise ToolError(ToolErrorKind.TIMEOUT, "模拟超时")

    spec: ToolSpec = replace(default_registry().require("query_cmdb"), handler=failing)
    registry = ToolRegistry()
    registry.register(spec)
    deps = AgentDeps(guard=ToolGuard(registry), retriever=None, top_k=5)
    return [
        event
        async for event in stream(
            run_id="run_replan",
            identity=EMPLOYEE,
            query="打印机离线",
            model="test",
            deps=deps,
        )
    ]


async def test_runtime_replans_once_then_degrades() -> None:
    events = await _run_with_failing_cmdb()
    types = [etype.value for etype, _ in events]
    steps = [payload["node"] for etype, payload in events if etype.value == "step.started"]

    assert steps.count("plan") == 2
    assert steps.count("verify") == 2
    assert types[-1] == "run.completed"

    answer = next(
        payload["text"] for etype, payload in events if etype.value == "message.completed"
    )
    assert "数据可能过期" in answer


def test_ticket_status_question_is_not_a_new_write() -> None:
    # 「我报修的」是过去时：问进度不能被 WRITE_KEYWORDS 里的「报修」误判成开单
    assert wants_ticket_status("我报修的打印机修好了吗") is True
    assert classify_intent("我报修的打印机修好了吗", "hardware") == "knowledge"
    assert needs_model("我的工单处理到哪了") is False

    # 明确的开单动作仍然优先
    assert classify_intent("帮我报修打印机", "hardware") == "ticket_create"
    assert classify_intent("帮我开一张报修工单", "hardware") == "ticket_create"


async def test_rule_plan_queries_tickets_for_status_question() -> None:
    state = initial_state(run_id="r1", user={"id": "u_102"}, query="我的工单处理到哪了")
    state["intent"] = "knowledge"
    plan = rule_plan(state)
    assert [call["tool"] for call in plan] == ["query_tickets"]
    assert plan[0]["args"] == {"limit": 5}

    write_state = initial_state(run_id="r2", user={"id": "u_102"}, query="帮我报修打印机")
    write_state["intent"] = "ticket_create"
    assert [call["tool"] for call in rule_plan(write_state)] == ["create_ticket"]


def test_finalize_answers_ticket_status_from_tool_result() -> None:
    state = initial_state(run_id="r1", user={"id": "u_102"}, query="我的工单到哪了")
    state["tool_results"] = [
        {
            "tool": "query_tickets",
            "status": "ok",
            "result": {
                "tickets": [
                    {
                        "id": "TCK-1A2B3C4D",
                        "title": "打印机离线",
                        "priority": "P2",
                        "status": "in_progress",
                        "created_at": "2026-11-11T09:00:00+00:00",
                    }
                ],
                "count": 1,
            },
        }
    ]
    answer, citations = compose_answer(state)
    assert "TCK-1A2B3C4D" in answer
    assert "处理中" in answer
    # 查自己的工单不需要知识库引用，也不能落成「知识库没有」的拒答
    assert citations == []
    assert "知识库里没有检索到" not in answer


def test_finalize_handles_empty_and_failed_ticket_query() -> None:
    empty = initial_state(run_id="r1", user={"id": "u_102"}, query="我的工单")
    empty["tool_results"] = [
        {"tool": "query_tickets", "status": "ok", "result": {"tickets": [], "count": 0}}
    ]
    answer, citations = compose_answer(empty)
    assert "没有查到工单" in answer
    assert citations == []

    failed = initial_state(run_id="r2", user={"id": "u_102"}, query="我的工单")
    failed["tool_results"] = [{"tool": "query_tickets", "status": "error", "result": None}]
    answer, _ = compose_answer(failed)
    assert "暂时没查到" in answer
