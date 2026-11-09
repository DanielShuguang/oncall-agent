"""多轮上下文（ADR-0020）。

**历史只来自服务端**：同一用户、同一会话里已经有回答的 run（`runs.input/output`
投影）。客户端不传历史——否则模型会把客户端伪造的"助手说过的话"当事实，
这比 R9 的入参身份泄漏更难发现。

三个边界，都是故意的：

1. **不是证据**：历史只用于理解指代（"那怎么办"）、拼检索词与模型规划上下文；
   引用仍然只能来自本轮的 `retrieved`，上一轮的切片不会自动变成引用
2. **有预算**：最多 3 轮 / 每条回答 400 字 / 总 1200 字；超了从最旧的丢。
   历史进的是 prompt，不设上限等于把上下文长度交给用户
3. **只认有回答的轮次**：挂起审批、正在跑、被中断的 run 没有 `output`，
   不当作历史；否则模型会"记得"一句它从未说过的话

追问判定是**关键词启发式**，不是模型改写：命中指代词/承接词才拼上一轮问题，
长句（>30 字）一律按新问题处理。宁可少用上下文，也不要把上一个话题硬塞进
一个本来能独立回答的问题——那会把新问题的召回稀释掉。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

MAX_TURNS = 3
MAX_QUERY_CHARS = 200
MAX_ANSWER_CHARS = 400
#: 3 轮 × (200 字问题 + 400 字回答) = 1800 字，所以预算比轮数更早生效：
#: 历史进 prompt，这里卡的是真实字符数，不是"最多几轮"这个抽象上限
MAX_CONTEXT_CHARS = 1200
#: 超过这个长度就当成信息完整的新问题：把上文拼进去只会稀释召回
FOLLOW_UP_MAX_CHARS = 30
#: 拼检索词时上文截断长度（够放一条完整问句，又不至于挤掉本轮关键词）
CONTEXT_QUERY_CHARS = 80

_FOLLOW_UP_PREFIXES = ("那", "再", "另外", "还有", "然后", "接着", "继续", "同样")
_FOLLOW_UP_MARKERS = (
    "它",
    "这个",
    "那个",
    "该文档",
    "该设备",
    "该工具",
    "该问题",
    "上述",
    "刚才",
    "上面",
    "前面",
    "这条",
    "这项",
    "同样",
)
_FOLLOW_UP_SUFFIXES = ("呢",)

Message = dict[str, str]


class TurnLike(Protocol):
    """`core.store.RunTurn` 的结构；这里用协议避免 agent 依赖存储层。"""

    @property
    def query(self) -> str: ...

    @property
    def answer(self) -> str: ...


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    query: str
    answer: str


def _shorten(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_messages(turns: Iterable[TurnLike]) -> list[Message]:
    """把历史轮次摊平成 `messages`（user/assistant 交替），只保留最近的预算内轮次。"""
    pending = list(turns)[-MAX_TURNS:]
    messages: list[Message] = []
    used = 0
    # 从最新往回装：预算不够时丢更早的轮次，而不是丢最新一轮
    for turn in reversed(pending):
        query = _shorten(str(getattr(turn, "query", "")), MAX_QUERY_CHARS)
        answer = _shorten(str(getattr(turn, "answer", "")), MAX_ANSWER_CHARS)
        if not query or not answer:
            continue
        cost = len(query) + len(answer)
        if messages and used + cost > MAX_CONTEXT_CHARS:
            break
        messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": query})
        used += cost
    messages.reverse()
    return messages


def needs_context(query: str) -> bool:
    """当前问题是承接上一轮的追问吗？（纯关键词判断，见模块文档）"""
    text = query.strip()
    if not text or len(text) > FOLLOW_UP_MAX_CHARS:
        return False
    if text.startswith(_FOLLOW_UP_PREFIXES):
        return True
    if text.endswith(_FOLLOW_UP_SUFFIXES):
        return True
    return any(marker in text for marker in _FOLLOW_UP_MARKERS)


def last_user_query(messages: Sequence[Message]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "user" and message.get("content", "").strip():
            return message["content"].strip()
    return None


def contextual_query(query: str, messages: Sequence[Message]) -> str:
    """检索用的查询：追问时把上一轮问题拼在前面，否则原样返回（不改变单轮行为）。"""
    text = query.strip()
    previous = last_user_query(messages)
    if not previous or not needs_context(text):
        return text
    return f"{_shorten(previous, CONTEXT_QUERY_CHARS)} {text}"
