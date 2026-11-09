"""classify / plan 的模型路径（W4 D16）：兜底、校验、身份注入、预算失败。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.agent.deps import AgentDeps
from app.agent.nodes.classify import classify_node, needs_model
from app.agent.nodes.plan import plan_node
from app.agent.runtime import stream
from app.agent.state import initial_state
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    Completion,
    ModelUnavailable,
    ModelUsage,
    Purpose,
)
from app.tools.builtin import default_registry
from app.tools.registry import Identity, ToolGuard

EMPLOYEE = Identity(user_id="u_102", roles=frozenset({"employee"}))


class FakeGateway:
    def __init__(self, responses: dict[Purpose, list[str | Exception]]) -> None:
        self.responses = {purpose: list(items) for purpose, items in responses.items()}
        self.calls: list[dict[str, Any]] = []

    def default_model(self) -> str:
        return "fake-model"

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        purpose: Purpose,
        run_id: str,
        step: str,
        user_id: str,
        spent_cents: int = 0,
        max_tokens: int | None = None,
        json_mode: bool = False,
        requested_model: str | None = None,
    ) -> Completion:
        self.calls.append(
            {
                "purpose": purpose,
                "run_id": run_id,
                "step": step,
                "spent_cents": spent_cents,
                "messages": messages,
            }
        )
        items = self.responses.get(purpose, [])
        item = items.pop(0) if items else '{"intent":"knowledge","incident_type":"other"}'
        if isinstance(item, Exception):
            raise item
        return Completion(
            text=item,
            model="fake-model",
            provider="local",
            token_in=10,
            token_out=5,
            cost_cents=1,
            latency_ms=5,
        )


def _deps(gateway: FakeGateway | None, **kwargs: Any) -> AgentDeps:
    return AgentDeps(guard=ToolGuard(default_registry()), gateway=gateway, **kwargs)


def _state(query: str, **overrides: Any) -> Any:
    state = initial_state(
        run_id="r1",
        user={"id": "u_102", "roles": ["employee"]},
        query=query,
    )
    state.update(overrides)
    return state


def test_needs_model_only_for_ambiguous_input() -> None:
    assert needs_model("报销流程怎么走")
    assert not needs_model("打印机离线")
    assert not needs_model("帮我开单")
    assert not needs_model("你好")


async def test_classify_uses_model_fallback_and_counts_usage() -> None:
    gateway = FakeGateway(
        {Purpose.CLASSIFY: ['{"intent":"asset_check","incident_type":"hardware"}']}
    )
    delta = await classify_node(_state("我想看看我的机器"), _deps(gateway))
    assert delta["intent"] == "asset_check"
    assert delta["classified_by"] == "llm"
    assert delta["usage"] == {"token_in": 10, "token_out": 5, "cost_cents": 1, "calls": 1}
    assert len(gateway.calls) == 1


async def test_classify_never_escalates_ambiguous_input_to_write() -> None:
    gateway = FakeGateway(
        {Purpose.CLASSIFY: ['{"intent":"ticket_create","incident_type":"hardware"}']}
    )
    delta = await classify_node(_state("报销流程怎么走"), _deps(gateway))
    # 模糊输入不能凭模型一句话升级成写操作（R10）
    assert delta["intent"] == "knowledge"
    assert delta["classified_by"] == "llm"


async def test_classify_falls_back_to_rule_on_model_error() -> None:
    gateway = FakeGateway({Purpose.CLASSIFY: [ModelUnavailable("down")]})
    delta = await classify_node(_state("报销流程怎么走"), _deps(gateway))
    assert delta["classified_by"] == "rule"
    assert delta["intent"] == "knowledge"
    assert delta["usage"]["calls"] == 0


async def test_plan_injects_owner_id_and_validates_calls() -> None:
    gateway = FakeGateway(
        {
            Purpose.PLAN: [
                '{"calls":[{"tool":"query_cmdb","args":{"owner_id":"u_evil"},"reason":"查设备"}]}'
            ]
        }
    )
    delta = await plan_node(_state("打印机离线", intent="asset_check"), _deps(gateway))
    assert delta["plan_source"] == "llm"
    assert delta["plan"][0]["tool"] == "query_cmdb"
    assert delta["plan"][0]["args"]["owner_id"] == "u_102"
    assert delta["usage"]["calls"] == 1


async def test_plan_drops_write_when_intent_is_not_ticket() -> None:
    gateway = FakeGateway(
        {
            Purpose.PLAN: [
                '{"calls":[{"tool":"create_ticket","args":{"title":"x",'
                '"category":"hardware","priority":"P2"}}]}'
            ]
        }
    )
    delta = await plan_node(_state("报销流程怎么走", intent="knowledge"), _deps(gateway))
    assert delta["plan"] == []
    assert delta["plan_source"] == "fallback"


async def test_plan_retries_once_then_falls_back() -> None:
    gateway = FakeGateway({Purpose.PLAN: ["不是 JSON", "还不是 JSON"]})
    delta = await plan_node(_state("打印机离线", intent="asset_check"), _deps(gateway))
    assert len(gateway.calls) == 2
    assert delta["plan_source"] == "fallback"
    assert delta["plan"][0]["tool"] == "query_cmdb"
    assert delta["usage"]["calls"] == 2


async def test_plan_propagates_budget_exceeded() -> None:
    gateway = FakeGateway({Purpose.PLAN: [BudgetExceeded("no money")]})
    with pytest.raises(BudgetExceeded):
        await plan_node(_state("打印机离线", intent="asset_check"), _deps(gateway))


async def test_runtime_accumulates_usage_into_run_completed() -> None:
    gateway = FakeGateway(
        {
            Purpose.CLASSIFY: ['{"intent":"knowledge","incident_type":"other"}'],
            Purpose.PLAN: ['{"calls":[]}'],
        }
    )
    events = [
        event
        async for event in stream(
            run_id="run_llm",
            identity=EMPLOYEE,
            query="报销流程怎么走",
            model="fake-model",
            deps=_deps(gateway),
        )
    ]
    completed = next(payload for etype, payload in events if etype.value == "run.completed")
    assert completed["token_in"] == 20
    assert completed["token_out"] == 10
    assert completed["cost_cents"] == 2

    summaries = [
        payload["summary"]
        for etype, payload in events
        if etype.value == "step.completed" and payload["node"] in {"classify", "plan"}
    ]
    assert any("模型兜底" in summary for summary in summaries)
    assert any("模型计划" in summary for summary in summaries)


async def test_runtime_budget_failure_becomes_run_failed() -> None:
    gateway = FakeGateway(
        {
            Purpose.CLASSIFY: ['{"intent":"knowledge","incident_type":"other"}'],
            Purpose.PLAN: [BudgetExceeded("当日预算已用尽")],
        }
    )
    events = [
        event
        async for event in stream(
            run_id="run_budget",
            identity=EMPLOYEE,
            query="报销流程怎么走",
            model="fake-model",
            deps=_deps(gateway),
        )
    ]
    failed = next(payload for etype, payload in events if etype.value == "run.failed")
    assert failed["error_code"] == "BUDGET_EXCEEDED"
    assert failed["category"] == "model"


def test_usage_merge() -> None:
    usage = ModelUsage(token_in=1, token_out=2, cost_cents=3, calls=1)
    merged = usage.merge(ModelUsage(token_in=10, token_out=20, cost_cents=30, calls=1))
    assert merged == ModelUsage(token_in=11, token_out=22, cost_cents=33, calls=2)
