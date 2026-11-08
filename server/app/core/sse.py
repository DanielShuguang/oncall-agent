"""SSE 帧编码。

协议见 docs/03-api-contract.md：
    id: <seq>
    event: <type>
    data: <json>
    <空行>
"""

from __future__ import annotations

import json
from typing import Any

HEARTBEAT_FRAME = ": heartbeat\n\n"


def encode_frame(*, seq: int | None, event: str, data: dict[str, Any]) -> str:
    """编码一帧 SSE。

    data 必须单行（json.dumps 默认不换行），否则前端按 \\n\\n 分帧会错。
    """
    lines: list[str] = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def encode_comment(text: str) -> str:
    """注释帧，用于保活，不占 seq。"""
    return f": {text}\n\n"
