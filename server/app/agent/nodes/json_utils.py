"""从模型输出里提取 JSON 对象（classify / plan 共用）。

模型可能返回裸 JSON、```json 代码块，或前后带解释文字；这里只做容错解析，
不判断字段是否合法——字段校验留给各节点（classify 的枚举、plan 的 validate_args）。
"""

from __future__ import annotations

import json
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    candidates = [stripped]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None
