"""结构切分：先按标题路径分段，段内超长再按句子递归。

目标 chunk 400-600 token（中文近似按字符计），重叠 80 token；
表格单独成 chunk 且保留表头 —— 表格被切碎是 RAG 最常见的翻车点。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.parse import Block, ParsedDoc

DEFAULT_TARGET_CHARS = 450
DEFAULT_OVERLAP_CHARS = 80
MIN_CHUNK_CHARS = 20
MAX_TABLE_CHARS = 6000

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;\n])")


@dataclass(frozen=True, slots=True)
class Chunk:
    ord: int
    text: str
    heading: str | None
    page: int | None = None
    is_table: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)


def chunk_parsed(
    parsed: ParsedDoc,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    if target_chars < 100:
        raise ValueError("target_chars 太小，切出来没有上下文")
    if overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("overlap_chars 必须在 [0, target_chars) 内")

    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_heading: str | None = None
    buffer_page: int | None = None

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        buffer = []
        if text:
            chunks.append(
                Chunk(
                    ord=len(chunks) + 1,
                    text=text,
                    # 没有标题层级的文档（比如纯文本）用文档标题兜底，引用里不至于空着
                    heading=buffer_heading or parsed.title,
                    page=buffer_page,
                )
            )

    for block in parsed.blocks:
        if block.is_table:
            flush()
            chunks.append(
                Chunk(
                    ord=len(chunks) + 1,
                    text=block.text[:MAX_TABLE_CHARS],
                    heading=block.heading_path or parsed.title,
                    page=block.page,
                    is_table=True,
                )
            )
            continue

        if buffer_heading != block.heading_path or buffer_page != block.page:
            flush()
            buffer_heading = block.heading_path
            buffer_page = block.page

        for piece in _split_long(block.text, target_chars, overlap_chars):
            if len(piece.strip()) < MIN_CHUNK_CHARS and buffer:
                buffer.append(piece)
                continue
            if buffer and _joined_len(buffer) + len(piece) + 1 > target_chars:
                flush()
            if len(piece) > target_chars:
                # 防御：_split_long 理论上不会超，真超了就按硬切兜底
                for start in range(0, len(piece), target_chars - overlap_chars):
                    flush()
                    buffer = [piece[start : start + target_chars]]
                    flush()
                continue
            buffer.append(piece)
    flush()

    return [chunk for chunk in chunks if chunk.text.strip()]


def _joined_len(parts: list[str]) -> int:
    return sum(len(part) for part in parts) + max(0, len(parts) - 1)


def _split_long(text: str, target: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= target:
        return [text]

    sentences = [part for part in _SENTENCE_END.split(text) if part.strip()]
    pieces: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        if len(sentence) > target:
            if current:
                pieces.append("".join(current).strip())
                current, current_len = [], 0
            step = max(1, target - overlap)
            for start in range(0, len(sentence), step):
                pieces.append(sentence[start : start + target].strip())
            continue

        if current_len + len(sentence) > target and current:
            pieces.append("".join(current).strip())
            tail = _overlap_tail(current, overlap)
            current = [tail] if tail else []
            current_len = len(tail)
        current.append(sentence)
        current_len += len(sentence)

    if current:
        pieces.append("".join(current).strip())
    return [piece for piece in pieces if piece]


def _overlap_tail(parts: list[str], overlap: int) -> str:
    if overlap <= 0:
        return ""
    tail: list[str] = []
    total = 0
    for part in reversed(parts):
        if total + len(part) > overlap:
            break
        tail.insert(0, part)
        total += len(part)
    return "".join(tail)


def chunk_blocks(
    title: str,
    blocks: list[Block],
    *,
    page_count: int | None = None,
) -> list[Chunk]:
    """给 seed/上传的纯块列表用；避免调用方自己拼 ParsedDoc。"""
    return chunk_parsed(ParsedDoc(title=title, blocks=blocks, page_count=page_count))
