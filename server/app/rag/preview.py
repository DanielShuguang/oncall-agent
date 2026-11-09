"""引用跳全文：把一篇文档的切片按 ord 重组成预览窗口。

放在 rag 层而不是路由里（R4）：「chunk_id 优先、ord 兜底、超长截断」是检索侧
对引用的约定，路由只负责鉴权与错误码。

可见性**不在这里判断**：谁能看文档由调用方保证（见 ADR-0018，预览与检索共用
同一可见性边界）。这里只负责窗口选择。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.rag.types import ChunkRow

#: 单次预览最多返回的切片数；50 篇种子文档最大也只有 10 段左右，这里是防护上限
MAX_PREVIEW_CHUNKS = 200
#: 单次预览的正文字符上限（防止一篇异常大文档把响应撑爆）
MAX_PREVIEW_CHARS = 200_000


@dataclass(frozen=True, slots=True)
class PreviewChunk:
    chunk_id: int
    ord: int
    heading: str | None
    content: str
    page: int | None


@dataclass(frozen=True, slots=True)
class DocumentPreview:
    """前端渲染所需的全部信息；`focused_chunk_id` 为空表示引用位置没对上。"""

    chunks: list[PreviewChunk]
    focused_chunk_id: int | None
    total_chunks: int
    truncated: bool


def build_preview(
    rows: Sequence[ChunkRow],
    *,
    chunk_id: int | None = None,
    ord: int | None = None,
) -> DocumentPreview:
    """把整篇切片裁成可返回的窗口，并标出引用命中的那一段。

    `chunk_id` 是引用自带的精确位置（docs/05 §6）；`ord` 是重排后的兜底。
    只按 chunk_id 找不到时不强行按 ord 猜——猜错会把读者带到错误段落，
    宁可不标焦点（前端提示「引用位置可能已变化」）。

    引用段一定优先保住：切片数超限时窗口前移，字符预算超限时直接从引用段
    重新开窗（宁可丢前文，也不让读者点了引用却看不到那一段）。
    """
    total = len(rows)
    focus_index = _find_focus(rows, chunk_id=chunk_id, ord=ord)

    start = 0
    if focus_index is not None and focus_index >= MAX_PREVIEW_CHUNKS:
        start = focus_index - MAX_PREVIEW_CHUNKS + 1
    window = rows[start : start + MAX_PREVIEW_CHUNKS]
    focus_rel = None if focus_index is None else focus_index - start

    chunks, included = _take(window, focus_rel)
    if focus_rel is not None and not included:
        chunks, _ = _take(window[focus_rel:], 0)

    focused = None
    if focus_index is not None:
        target = rows[focus_index].chunk_id
        focused = target if any(item.chunk_id == target for item in chunks) else None

    return DocumentPreview(
        chunks=chunks,
        focused_chunk_id=focused,
        total_chunks=total,
        truncated=len(chunks) < total,
    )


def _take(window: Sequence[ChunkRow], focus_rel: int | None) -> tuple[list[PreviewChunk], bool]:
    """从窗口头开始按字符预算取切片；`focus_rel` 是引用段在窗口内的下标。

    返回值第二项表示引用段是否落在取到的切片里（`focus_rel` 为 None 时恒为 False）。
    """
    chunks: list[PreviewChunk] = []
    used = 0
    for row in window:
        if chunks and used + len(row.content) > MAX_PREVIEW_CHARS:
            break
        chunks.append(
            PreviewChunk(
                chunk_id=row.chunk_id,
                ord=row.ord,
                heading=row.heading,
                content=row.content,
                page=row.page,
            )
        )
        used += len(row.content)
    included = focus_rel is not None and 0 <= focus_rel < len(chunks)
    return chunks, included


def _find_focus(rows: Sequence[ChunkRow], *, chunk_id: int | None, ord: int | None) -> int | None:
    if chunk_id is not None:
        for index, row in enumerate(rows):
            if row.chunk_id == chunk_id:
                return index
    if ord is not None:
        for index, row in enumerate(rows):
            if row.ord == ord:
                return index
    return None
