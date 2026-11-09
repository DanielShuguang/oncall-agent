"""模型网关（W4 D16–D18）。

一次 `chat()` 做五件事，顺序固定：

1. 按 purpose 规则路由（classify → local，plan/answer → cloud 优先）
2. 单 run 预算检查 + 当日预算预扣（Redis Lua 原子）
3. 调 provider；失败按配置顺序 failover
4. 按实际 token 结算，写 `model_calls`，同事务增量更新 `runs`
5. 返回 `Completion`，由节点累计成 state["usage"]

不做 LiteLLM：路由、降级、预算正是这个项目要讲的设计
（docs/decisions/0013-model-gateway.md）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import perf_counter

from app.core.config import Settings
from app.core.limits import BudgetLedger
from app.core.logging import get_logger
from app.gateway.meter import ModelCallRecord, ModelCallStore
from app.gateway.pricing import estimate_cost_cents, estimate_messages_tokens, estimate_tokens
from app.gateway.providers import build_provider
from app.gateway.router import order_for_purpose
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    Completion,
    MeteringError,
    ModelUnavailable,
    Provider,
    ProviderError,
    Purpose,
    Route,
)

log = get_logger(__name__)

ProviderFactory = Callable[[Route], Provider]


class ModelGateway:
    def __init__(
        self,
        routes: Sequence[Route],
        *,
        budget: BudgetLedger,
        meter: ModelCallStore,
        settings: Settings,
        provider_factory: ProviderFactory = build_provider,
    ) -> None:
        self._routes = list(routes)
        self._budget = budget
        self._meter = meter
        self._settings = settings
        self._provider_factory = provider_factory

    def default_model(self) -> str:
        ordered = order_for_purpose(self._routes, Purpose.PLAN)
        return ordered[0].model if ordered else "rule-engine"

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
        routes = order_for_purpose(self._routes, purpose, requested_model)
        if not routes:
            raise ModelUnavailable("没有可用的模型 provider（检查 ONCALL_MODEL_PROVIDERS）")

        limit_tokens = max(1, max_tokens or self._settings.model_max_tokens)
        limit_tokens = min(limit_tokens, self._settings.model_max_tokens)
        token_in_est = estimate_messages_tokens(messages)
        # 按所有候选路由里最贵的一档预扣：failover 可能切到更贵的 provider，
        # 只按首选路由预扣会让单 run / 当日预算在切换后被突破。
        reserved = max(estimate_cost_cents(route, token_in_est, limit_tokens) for route in routes)

        if spent_cents + reserved > self._settings.run_budget_cents:
            raise BudgetExceeded(
                f"单 run 成本超过 {self._settings.run_budget_cents} 分"
                f"（已用 {spent_cents}，预计 {reserved}）"
            )
        if not await self._budget.reserve(reserved):
            raise BudgetExceeded("当日模型预算已用尽")

        temperature = 0.0 if purpose is not Purpose.ANSWER else self._settings.model_temperature
        last_error = ""
        settled = False
        try:
            for index, route in enumerate(routes):
                provider = self._provider_factory(route)
                started = perf_counter()
                try:
                    raw = await provider.chat(
                        messages,
                        max_tokens=limit_tokens,
                        temperature=temperature,
                        json_mode=json_mode,
                    )
                except ProviderError as exc:
                    latency_ms = _ms(started)
                    last_error = str(exc)
                    log.warning(
                        "model_call_failed",
                        run_id=run_id,
                        purpose=purpose.value,
                        provider=route.provider,
                        model=route.model,
                        latency_ms=latency_ms,
                        error=last_error,
                    )
                    await self._record_error(
                        run_id=run_id,
                        step=step,
                        user_id=user_id,
                        route=route,
                        latency_ms=latency_ms,
                        error=last_error,
                    )
                    continue

                latency_ms = _ms(started)
                token_in = raw.token_in if raw.token_in is not None else token_in_est
                token_out = (
                    raw.token_out if raw.token_out is not None else estimate_tokens(raw.text)
                )
                cost_cents = estimate_cost_cents(route, token_in, token_out)
                await self._budget.settle(reserved, cost_cents)
                settled = True

                completion = Completion(
                    text=raw.text,
                    model=route.model,
                    provider=route.provider,
                    token_in=token_in,
                    token_out=token_out,
                    cost_cents=cost_cents,
                    latency_ms=latency_ms,
                    first_token_ms=raw.first_token_ms,
                )
                status = "ok" if index == 0 else "fallback"
                try:
                    await self._meter.record(
                        ModelCallRecord(
                            run_id=run_id,
                            step=step,
                            provider=route.provider,
                            model=route.model,
                            token_in=token_in,
                            token_out=token_out,
                            cost_cents=cost_cents,
                            latency_ms=latency_ms,
                            first_token_ms=raw.first_token_ms,
                            status=status,
                            error=None,
                            user_id=user_id,
                        )
                    )
                except Exception as exc:
                    # 没有 model_calls 的 token 会让看板与 runs 对不上，直接让 run 失败
                    raise MeteringError(f"计量写入失败: {exc}") from exc

                log.info(
                    "model_call",
                    run_id=run_id,
                    purpose=purpose.value,
                    step=step,
                    provider=route.provider,
                    model=route.model,
                    token_in=token_in,
                    token_out=token_out,
                    cost_cents=cost_cents,
                    latency_ms=latency_ms,
                    status=status,
                )
                return completion
        finally:
            if not settled:
                # provider 抛非 ProviderError 时也要归还预扣，避免预算泄漏
                await self._budget.settle(reserved, 0)

        raise ModelUnavailable(f"所有模型 provider 均失败: {last_error}")

    async def _record_error(
        self,
        *,
        run_id: str,
        step: str,
        user_id: str,
        route: Route,
        latency_ms: int,
        error: str,
    ) -> None:
        try:
            await self._meter.record(
                ModelCallRecord(
                    run_id=run_id,
                    step=step,
                    provider=route.provider,
                    model=route.model,
                    token_in=0,
                    token_out=0,
                    cost_cents=0,
                    latency_ms=latency_ms,
                    first_token_ms=None,
                    status="error",
                    error=error[:500],
                    user_id=user_id,
                )
            )
        except Exception as exc:  # 失败尝试的计量不值得再拖垮 failover
            log.warning("model_call_error_record_failed", run_id=run_id, error=str(exc))


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def build_gateway(
    *,
    settings: Settings,
    routes: Sequence[Route],
    budget: BudgetLedger,
    meter: ModelCallStore,
    provider_factory: ProviderFactory = build_provider,
) -> ModelGateway:
    return ModelGateway(
        routes,
        budget=budget,
        meter=meter,
        settings=settings,
        provider_factory=provider_factory,
    )


__all__ = ["ModelGateway", "build_gateway"]
