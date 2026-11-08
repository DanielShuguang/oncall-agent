"""模型网关（W4 D16 起实现）。

职责：provider 适配、规则路由、失败切换、token 计量、预算预扣。
刻意不引入 LiteLLM：路由/降级/预算正是要讲的设计，不能被配置化掉。

接口草案：

    class Gateway:
        async def chat(self, messages, *, purpose: str, run_id: str) -> Completion
        # purpose: classify | plan | answer —— 决定走小模型还是大模型
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Completion:
    text: str
    model: str
    provider: str
    token_in: int
    token_out: int
    cost_cents: int
    first_token_ms: int | None = None
    latency_ms: int = 0


class GatewayNotImplemented(RuntimeError):
    pass


async def chat(messages: list[dict[str, Any]], *, purpose: str, run_id: str) -> Completion:
    raise GatewayNotImplemented("模型网关将在 W4 D16 实现，见 docs/01-architecture.md")
