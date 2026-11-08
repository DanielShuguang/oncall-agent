"""intake 节点：规则清洗输入。

W3 D11 会在这里补上用户上下文与资产缓存；现在只做规范化，
保证后续节点看到的 query 是去空白后的单行文本。
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import AgentState

_WHITESPACE = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def intake_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：规范化后的 query。"""
    del deps  # 规则节点不需要依赖，签名保持统一便于后续换 LLM
    return {"query": normalize_query(state.get("query", ""))}
