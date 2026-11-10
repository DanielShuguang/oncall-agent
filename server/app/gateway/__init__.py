"""模型网关（W4 D16 起实现）。

职责：provider 适配、规则路由、失败切换、token 计量、预算预扣。
刻意不引入 LiteLLM：路由/降级/预算正是要讲的设计，不能被配置化掉。

    gateway = get_gateway()
    completion = await gateway.chat(messages, purpose=Purpose.PLAN, run_id=..., step="plan")

`ONCALL_MOCK_MODE=true` 时不经过网关：节点走确定性规则，成本恒为 0
（W6 D28 的无 key 演示模式）。
"""

from __future__ import annotations

from app.budgets.policy import get_user_budget_policy
from app.core.config import Settings, get_settings
from app.core.limits import get_budget_ledger, get_user_budget_ledger
from app.gateway.gateway import ModelGateway, build_gateway
from app.gateway.meter import get_model_call_store
from app.gateway.router import build_routes, default_model
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    Completion,
    GatewayError,
    MeteringError,
    ModelUnavailable,
    ModelUsage,
    ProviderError,
    Purpose,
)
from app.gateway.types import (
    ModelGateway as ModelGatewayProtocol,
)

_gateway: ModelGateway | None = None


def get_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        settings = get_settings()
        _gateway = build_gateway(
            settings=settings,
            routes=build_routes(settings),
            budget=get_budget_ledger(),
            meter=get_model_call_store(),
            user_budget=get_user_budget_ledger(),
            user_limits=get_user_budget_policy(),
        )
    return _gateway


def set_gateway(value: ModelGateway | None) -> None:
    """测试钩子；生产启动时不要调用。"""
    global _gateway
    _gateway = value


def default_model_name(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.mock_mode:
        return "rule-engine"
    return default_model(settings)


__all__ = [
    "BudgetExceeded",
    "ChatMessage",
    "Completion",
    "GatewayError",
    "MeteringError",
    "ModelGateway",
    "ModelGatewayProtocol",
    "ModelUnavailable",
    "ModelUsage",
    "ProviderError",
    "Purpose",
    "default_model_name",
    "get_gateway",
    "set_gateway",
]
