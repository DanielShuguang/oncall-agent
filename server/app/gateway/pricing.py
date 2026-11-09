"""token 估算与计价（W4 D18）。

计价口径（写进 docs/02 §2.4、docs/08）：
- 单价来自配置，单位「分 / 百万 token」，不是美元
- 成本向上取整到分；只要单价 > 0 且产生 token，至少记 1 分，避免免费调用
- usage 缺失时按字符估算：CJK 约 1 字 1 token，其他约 4 字符 1 token
"""

from __future__ import annotations

from collections.abc import Sequence

from app.gateway.types import ChatMessage, Route

TOKENS_PER_MILLION = 1_000_000


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF  # 常用汉字
        or 0x3400 <= code <= 0x4DBF  # 扩展 A
        or 0x3040 <= code <= 0x30FF  # 日文假名
        or 0xAC00 <= code <= 0xD7AF  # 韩文
    )


def estimate_tokens(text: str) -> int:
    """保守估算：CJK 按 1 字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for char in text if _is_cjk(char))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def estimate_messages_tokens(messages: Sequence[ChatMessage]) -> int:
    # 每条消息的角色/分隔符按 4 token 估，宁可多留预算
    return sum(estimate_tokens(message.content) + 4 for message in messages) + 2


def estimate_cost_cents(route: Route, token_in: int, token_out: int) -> int:
    numerator = token_in * route.price_in_cents_per_1m + token_out * route.price_out_cents_per_1m
    if numerator <= 0:
        return 0
    cost = (numerator + TOKENS_PER_MILLION - 1) // TOKENS_PER_MILLION
    return max(1, cost)
