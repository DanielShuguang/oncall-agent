"""节点提示词（版本化）。

提示词改动必须跑 `make eval` 并对比基线（docs/08 §6）；版本号写进评测报告，
否则无法回答「这次指标变化是提示词还是检索造成的」。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

PROMPT_VERSIONS = {
    "classify": "v1",
    "plan": "v1",
}


@lru_cache
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"提示词不存在: {name}")
    return path.read_text(encoding="utf-8").strip()
