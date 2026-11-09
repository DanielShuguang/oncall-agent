"""网关类型与协议。

`agent` 只依赖这里的 `ModelGateway` 协议，不 import 具体 provider；
`gateway` 不做业务判断（docs/01 §2），所以类型里没有 intent / plan。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class Purpose(StrEnum):
    """调用目的，规则路由的唯一输入（小模型 / 大模型）。"""

    CLASSIFY = "classify"
    PLAN = "plan"
    ANSWER = "answer"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str

    def as_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class Route:
    """一条可调用的 provider 路由。价格单位：分 / 百万 token。"""

    provider: str
    model: str
    base_url: str
    api_key: str
    price_in_cents_per_1m: int
    price_out_cents_per_1m: int
    timeout_s: float


@dataclass(frozen=True, slots=True)
class RawCompletion:
    """provider 原始返回；usage 缺失时为 None，由网关估算。"""

    text: str
    token_in: int | None = None
    token_out: int | None = None
    first_token_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    model: str
    provider: str
    token_in: int
    token_out: int
    cost_cents: int
    latency_ms: int
    first_token_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """一个 run 的累计用量；节点把它放回 state，runtime 写进 run.completed。"""

    token_in: int = 0
    token_out: int = 0
    cost_cents: int = 0
    calls: int = 0

    def add(self, completion: Completion) -> ModelUsage:
        return ModelUsage(
            token_in=self.token_in + completion.token_in,
            token_out=self.token_out + completion.token_out,
            cost_cents=self.cost_cents + completion.cost_cents,
            calls=self.calls + 1,
        )

    def merge(self, other: ModelUsage) -> ModelUsage:
        return ModelUsage(
            token_in=self.token_in + other.token_in,
            token_out=self.token_out + other.token_out,
            cost_cents=self.cost_cents + other.cost_cents,
            calls=self.calls + other.calls,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "token_in": self.token_in,
            "token_out": self.token_out,
            "cost_cents": self.cost_cents,
            "calls": self.calls,
        }

    @classmethod
    def from_dict(cls, value: Any) -> ModelUsage:
        if not isinstance(value, dict):
            return cls()
        return cls(
            token_in=_as_int(value.get("token_in")),
            token_out=_as_int(value.get("token_out")),
            cost_cents=_as_int(value.get("cost_cents")),
            calls=_as_int(value.get("calls")),
        )


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class Provider(Protocol):
    route: Route

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> RawCompletion: ...


class ModelGateway(Protocol):
    def default_model(self) -> str: ...

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
    ) -> Completion: ...


class GatewayError(RuntimeError):
    """网关错误基类；调用方按类型决定降级还是失败。"""


class ModelUnavailable(GatewayError):
    """所有 provider 都失败；classify 可降级，plan 可退回规则计划。"""


class BudgetExceeded(GatewayError):
    """单 run 或当日预算不足；run 应收敛到 run.failed(BUDGET_EXCEEDED)。"""


class MeteringError(GatewayError):
    """计量写入失败；宁可让 run 失败，也不能产生没有 model_calls 的 token。"""


class ProviderError(GatewayError):
    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
