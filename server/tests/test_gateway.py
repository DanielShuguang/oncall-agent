"""模型网关：路由、计价、failover、预算、计量（W4 D16–D18）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.core.config import Settings
from app.core.limits import InMemoryBudgetLedger, InMemoryRateLimiter
from app.gateway.gateway import ModelGateway
from app.gateway.meter import InMemoryModelCallStore, ModelCallRecord
from app.gateway.pricing import estimate_cost_cents, estimate_tokens
from app.gateway.router import order_for_purpose
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    Completion,
    MeteringError,
    ModelUnavailable,
    ProviderError,
    Purpose,
    RawCompletion,
    Route,
)

CLOUD = Route(
    provider="cloud",
    model="gpt-test",
    base_url="http://cloud",
    api_key="k",
    price_in_cents_per_1m=15,
    price_out_cents_per_1m=60,
    timeout_s=1.0,
)
LOCAL = Route(
    provider="local",
    model="qwen-test",
    base_url="http://local/v1",
    api_key="",
    price_in_cents_per_1m=0,
    price_out_cents_per_1m=0,
    timeout_s=1.0,
)


class FakeProvider:
    def __init__(self, route: Route, result: RawCompletion | Exception) -> None:
        self.route = route
        self.result = result
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
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "store_backend": "memory",
        "mock_mode": False,
        "model_max_tokens": 100,
        "run_budget_cents": 50,
        "daily_budget_cny": 5,
    }
    values.update(overrides)
    return Settings(**values)


def _gateway(
    routes: list[Route],
    *,
    provider: FakeProvider | None = None,
    budget_cents: int = 1000,
    meter: InMemoryModelCallStore | None = None,
) -> tuple[ModelGateway, InMemoryModelCallStore, FakeProvider]:
    calls = meter or InMemoryModelCallStore()
    fake = provider or FakeProvider(routes[0], RawCompletion("ok", 100, 20))

    def factory(route: Route) -> FakeProvider:
        if route == fake.route:
            return fake
        return FakeProvider(route, RawCompletion("fallback", 10, 5))

    gateway = ModelGateway(
        routes,
        budget=InMemoryBudgetLedger(budget_cents),
        meter=calls,
        settings=_settings(),
        provider_factory=factory,
    )
    return gateway, calls, fake


def test_router_prefers_local_for_classify_and_cloud_for_plan() -> None:
    assert order_for_purpose([LOCAL, CLOUD], Purpose.CLASSIFY)[0].provider == "local"
    assert order_for_purpose([LOCAL, CLOUD], Purpose.PLAN)[0].provider == "cloud"
    assert order_for_purpose([LOCAL, CLOUD], Purpose.ANSWER)[0].provider == "cloud"


def test_requested_model_moves_to_front_only_when_configured() -> None:
    ordered = order_for_purpose([LOCAL, CLOUD], Purpose.PLAN, requested_model="qwen-test")
    assert ordered[0].provider == "local"
    # 未配置的模型不生效，避免客户端指定任意模型
    assert order_for_purpose([LOCAL, CLOUD], Purpose.PLAN, "gpt-4")[0].provider == "cloud"


def test_pricing_uses_cents_and_rounds_up() -> None:
    # (100*15 + 20*60) / 1e6 = 0.0027 元 → 向上取整 1 分
    assert estimate_cost_cents(CLOUD, 100, 20) == 1
    assert estimate_cost_cents(LOCAL, 100, 20) == 0
    # 1M token 正好是单价（分）
    assert estimate_cost_cents(CLOUD, 1_000_000, 0) == 15


def test_token_estimate_handles_cjk() -> None:
    assert estimate_tokens("打印机") == 3
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1


async def test_chat_records_usage_and_cost() -> None:
    gateway, records, _ = _gateway([CLOUD])
    completion = await gateway.chat(
        [ChatMessage(role="user", content="hi")],
        purpose=Purpose.PLAN,
        run_id="r1",
        step="plan",
        user_id="u_102",
    )
    assert completion.provider == "cloud"
    assert completion.cost_cents == 1
    assert len(records.records) == 1
    record = records.records[0]
    assert record.status == "ok"
    assert record.token_in == 100
    assert record.token_out == 20
    assert record.cost_cents == 1
    assert record.run_id == "r1"
    assert record.user_id == "u_102"


async def test_chat_fails_over_and_marks_fallback() -> None:
    cloud = FakeProvider(CLOUD, ProviderError("boom", retryable=True))
    gateway = ModelGateway(
        [LOCAL, CLOUD],
        budget=InMemoryBudgetLedger(1000),
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: (
            cloud if route == CLOUD else FakeProvider(route, RawCompletion("local ok", 10, 5))
        ),
    )
    completion = await gateway.chat(
        [ChatMessage(role="user", content="hi")],
        purpose=Purpose.PLAN,
        run_id="r2",
        step="plan",
        user_id="u_102",
    )
    assert completion.provider == "local"
    assert completion.text == "local ok"


async def test_chat_raises_when_all_providers_fail() -> None:
    failing = ProviderError("down", retryable=True)
    gateway = ModelGateway(
        [CLOUD],
        budget=InMemoryBudgetLedger(1000),
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: FakeProvider(route, failing),
    )
    with pytest.raises(ModelUnavailable):
        await gateway.chat(
            [ChatMessage(role="user", content="hi")],
            purpose=Purpose.PLAN,
            run_id="r3",
            step="plan",
            user_id="u_102",
        )


async def test_daily_budget_rejects_before_calling_provider() -> None:
    gateway, records, fake = _gateway([CLOUD], budget_cents=0)
    # 估算成本 > 1 分，直接拒绝，provider 一次都不能调
    with pytest.raises(BudgetExceeded):
        await gateway.chat(
            [ChatMessage(role="user", content="x" * 500)],
            purpose=Purpose.PLAN,
            run_id="r4",
            step="plan",
            user_id="u_102",
            max_tokens=1000,
        )
    assert fake.calls == 0
    assert records.records == []


async def test_run_budget_rejects_when_spent_is_high() -> None:
    gateway, _, fake = _gateway([CLOUD])
    with pytest.raises(BudgetExceeded):
        await gateway.chat(
            [ChatMessage(role="user", content="x" * 500)],
            purpose=Purpose.PLAN,
            run_id="r5",
            step="plan",
            user_id="u_102",
            spent_cents=50,
        )
    assert fake.calls == 0


async def test_reservation_covers_failover_to_expensive_route() -> None:
    """预扣要覆盖最贵候选：classify 首选 local 失败后切到 cloud 也会花真钱。"""
    ledger = InMemoryBudgetLedger(0)
    local = FakeProvider(LOCAL, ProviderError("local down", retryable=True))
    cloud = FakeProvider(CLOUD, RawCompletion("cloud ok", 10, 5))
    gateway = ModelGateway(
        [LOCAL, CLOUD],
        budget=ledger,
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: local if route == LOCAL else cloud,
    )
    with pytest.raises(BudgetExceeded):
        await gateway.chat(
            [ChatMessage(role="user", content="hi")],
            purpose=Purpose.CLASSIFY,
            run_id="r7",
            step="classify",
            user_id="u_102",
        )
    # 预算在调用前拒绝，两个 provider 一次都不能调
    assert local.calls == 0
    assert cloud.calls == 0


async def test_budget_settles_actual_after_success() -> None:
    ledger = InMemoryBudgetLedger(1000)
    gateway = ModelGateway(
        [CLOUD],
        budget=ledger,
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: FakeProvider(route, RawCompletion("ok", 100, 20)),
    )
    await gateway.chat(
        [ChatMessage(role="user", content="hi")],
        purpose=Purpose.PLAN,
        run_id="r8",
        step="plan",
        user_id="u_102",
    )
    # 成功路径按实际成本结算；finally 不能把已结算的预扣再退一次
    assert await ledger.spent() == 1


async def test_unexpected_provider_error_refunds_reservation() -> None:
    ledger = InMemoryBudgetLedger(1000)
    gateway = ModelGateway(
        [CLOUD],
        budget=ledger,
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: FakeProvider(route, RuntimeError("bug")),
    )
    with pytest.raises(RuntimeError):
        await gateway.chat(
            [ChatMessage(role="user", content="hi")],
            purpose=Purpose.PLAN,
            run_id="r9",
            step="plan",
            user_id="u_102",
        )
    assert await ledger.spent() == 0


async def test_metering_failure_is_fatal() -> None:
    class BrokenMeter(InMemoryModelCallStore):
        async def record(self, record: ModelCallRecord) -> None:
            raise RuntimeError("db down")

    gateway = ModelGateway(
        [CLOUD],
        budget=InMemoryBudgetLedger(1000),
        meter=BrokenMeter(),
        settings=_settings(),
        provider_factory=lambda route: FakeProvider(route, RawCompletion("ok", 100, 20)),
    )
    with pytest.raises(MeteringError):
        await gateway.chat(
            [ChatMessage(role="user", content="hi")],
            purpose=Purpose.PLAN,
            run_id="r6",
            step="plan",
            user_id="u_102",
        )


async def test_rate_limiter_sliding_window() -> None:
    limiter = InMemoryRateLimiter(limit=2)
    assert await limiter.allow("u_102")
    assert await limiter.allow("u_102")
    assert not await limiter.allow("u_102")
    # 不同用户互不影响
    assert await limiter.allow("u_205")


async def test_budget_ledger_reserves_and_settles() -> None:
    ledger = InMemoryBudgetLedger(limit_cents=10)
    assert await ledger.reserve(6)
    assert not await ledger.reserve(6)
    await ledger.settle(6, 2)
    assert await ledger.spent() == 2
    assert await ledger.reserve(8)


def test_completion_shape() -> None:
    completion = Completion(
        text="x",
        model="m",
        provider="local",
        token_in=1,
        token_out=2,
        cost_cents=0,
        latency_ms=3,
    )
    assert completion.first_token_ms is None
