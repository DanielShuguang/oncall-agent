"""真实网关路径的端到端校验：SSE -> model_calls -> run 详情 -> 成本汇总。"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.core.limits import InMemoryBudgetLedger
from app.gateway import set_gateway
from app.gateway.gateway import ModelGateway
from app.gateway.meter import InMemoryModelCallStore
from app.gateway.types import ChatMessage, RawCompletion, Route


class QueueProvider:
    def __init__(self, route: Route, responses: list[RawCompletion]) -> None:
        self.route = route
        self.responses = responses
        self.calls = 0

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> RawCompletion:
        self.calls += 1
        return self.responses.pop(0)


def _parse(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


@pytest.fixture
def real_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ONCALL_MOCK_MODE", "false")
    get_settings.cache_clear()
    yield
    set_gateway(None)
    monkeypatch.delenv("ONCALL_MOCK_MODE", raising=False)
    get_settings.cache_clear()


async def test_chat_with_gateway_persists_model_calls(
    client: AsyncClient,
    mem_model_calls: InMemoryModelCallStore,
    real_mode: None,
) -> None:
    route = Route(
        provider="local",
        model="fake-model",
        base_url="http://fake",
        api_key="",
        price_in_cents_per_1m=15,
        price_out_cents_per_1m=60,
        timeout_s=1.0,
    )
    provider = QueueProvider(
        route,
        [
            RawCompletion('{"intent":"knowledge","incident_type":"other"}', 10, 5),
            RawCompletion('{"calls":[]}', 10, 5),
        ],
    )
    settings = Settings(
        store_backend="memory",
        mock_mode=False,
        model_max_tokens=100,
        run_budget_cents=50,
        daily_budget_cny=5,
    )
    gateway = ModelGateway(
        [route],
        budget=InMemoryBudgetLedger(1000),
        meter=mem_model_calls,
        settings=settings,
        provider_factory=lambda _route: provider,
    )
    set_gateway(gateway)

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"session_id": "s", "message": "报销流程怎么走"},
    ) as res:
        assert res.status_code == 200
        lines = [line async for line in res.aiter_lines()]

    events = _parse(lines)
    completed = next(e for e in events if e["type"] == "run.completed")
    assert completed["payload"]["token_in"] == 20
    assert completed["payload"]["token_out"] == 10
    assert completed["payload"]["cost_cents"] == 2

    run_id = str(events[0]["run_id"])
    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert len(detail["model_calls"]) == 2
    assert [call["step"] for call in detail["model_calls"]] == ["classify", "plan"]
    assert detail["cost_cents"] == 2
    assert sum(call["cost_cents"] for call in detail["model_calls"]) == detail["cost_cents"]
