"""规则路由：按调用目的选 provider（W4 D16）。

不是让模型决定用哪个模型，而是配置 + 固定规则：

    classify → local（小模型，便宜、低延迟）
    plan / answer → cloud 优先，未配置时回落 local

`ONCALL_MODEL_PROVIDERS` 只控制启用哪些 provider，不改变上面的优先序；
`options.model` 只能覆盖到已配置的模型，避免客户端指定任意模型名。
"""

from __future__ import annotations

from app.core.config import Settings
from app.gateway.types import Purpose, Route


def build_routes(settings: Settings) -> list[Route]:
    enabled = set(settings.provider_names)
    routes: list[Route] = []
    if "cloud" in enabled and settings.cloud_configured:
        routes.append(
            Route(
                provider="cloud",
                model=settings.cloud_model,
                base_url=settings.cloud_base_url,
                api_key=settings.cloud_api_key,
                price_in_cents_per_1m=settings.cloud_price_in_cents_per_1m,
                price_out_cents_per_1m=settings.cloud_price_out_cents_per_1m,
                timeout_s=settings.model_request_timeout_s,
            )
        )
    if "local" in enabled and settings.local_configured:
        routes.append(
            Route(
                provider="local",
                model=settings.local_model,
                base_url=settings.local_base_url,
                api_key=settings.local_api_key,
                price_in_cents_per_1m=settings.local_price_in_cents_per_1m,
                price_out_cents_per_1m=settings.local_price_out_cents_per_1m,
                timeout_s=settings.model_request_timeout_s,
            )
        )
    return routes


def order_for_purpose(
    routes: list[Route],
    purpose: Purpose,
    requested_model: str | None = None,
) -> list[Route]:
    preferred = "local" if purpose is Purpose.CLASSIFY else "cloud"
    ordered = sorted(routes, key=lambda route: 0 if route.provider == preferred else 1)
    if requested_model:
        matched = [route for route in ordered if route.model == requested_model]
        if matched:
            ordered = matched + [route for route in ordered if route.model != requested_model]
    return ordered


def default_model(settings: Settings) -> str:
    """`run.started.model` 用 plan 的首选模型：这是本 run 最可能的真实模型。"""
    routes = order_for_purpose(build_routes(settings), Purpose.PLAN)
    return routes[0].model if routes else "rule-engine"
