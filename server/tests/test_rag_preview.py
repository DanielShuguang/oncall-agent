"""引用跳全文的窗口选择：chunk_id 优先、ord 兜底、超长截断（纯函数）。"""

from __future__ import annotations

from app.rag.preview import MAX_PREVIEW_CHARS, MAX_PREVIEW_CHUNKS, build_preview
from app.rag.types import ChunkRow


def _row(chunk_id: int, ordinal: int, *, content: str = "正文内容", heading: str | None = None):
    return ChunkRow(
        chunk_id=chunk_id,
        document_id="doc_1",
        ord=ordinal,
        title="测试文档",
        source="doc.md",
        heading=heading,
        content=content,
        page=None,
        tokens="",
    )


def test_focus_by_chunk_id_and_keeps_order() -> None:
    rows = [_row(11, 1), _row(12, 2), _row(13, 3)]

    preview = build_preview(rows, chunk_id=12)

    assert [chunk.chunk_id for chunk in preview.chunks] == [11, 12, 13]
    assert preview.focused_chunk_id == 12
    assert preview.total_chunks == 3
    assert preview.truncated is False


def test_focus_falls_back_to_ord_when_chunk_id_is_stale() -> None:
    rows = [_row(11, 1), _row(12, 2)]

    preview = build_preview(rows, chunk_id=999, ord=2)

    assert preview.focused_chunk_id == 12


def test_focus_missing_does_not_guess() -> None:
    """chunk_id / ord 都对不上时不硬挑一段：猜错会把读者带到错误段落。"""
    rows = [_row(11, 1), _row(12, 2)]

    preview = build_preview(rows, chunk_id=999, ord=99)

    assert preview.focused_chunk_id is None
    assert len(preview.chunks) == 2


def test_window_shifts_to_include_focus_beyond_chunk_cap() -> None:
    rows = [_row(index, index) for index in range(1, MAX_PREVIEW_CHUNKS + 6)]
    focus = rows[-1]

    preview = build_preview(rows, chunk_id=focus.chunk_id)

    assert len(preview.chunks) == MAX_PREVIEW_CHUNKS
    assert preview.chunks[0].ord == rows[0].ord + 5
    assert preview.focused_chunk_id == focus.chunk_id
    assert preview.truncated is True


def test_char_budget_truncates_tail_but_keeps_focus() -> None:
    big = "x" * (MAX_PREVIEW_CHARS - 1)
    rows = [_row(11, 1, content=big), _row(12, 2, content=big)]

    preview = build_preview(rows, chunk_id=12)

    # 预算在引用段之前用尽：丢掉前文，从引用段重新开窗，焦点必须保住
    assert [chunk.chunk_id for chunk in preview.chunks] == [12]
    assert preview.focused_chunk_id == 12
    assert preview.truncated is True


def test_char_budget_keeps_earlier_focus_with_its_context() -> None:
    big = "x" * (MAX_PREVIEW_CHARS - 1)
    rows = [_row(11, 1, content=big), _row(12, 2, content=big), _row(13, 3, content=big)]

    preview = build_preview(rows, chunk_id=11)

    assert [chunk.chunk_id for chunk in preview.chunks] == [11]
    assert preview.focused_chunk_id == 11
    assert preview.truncated is True


def test_empty_document_returns_empty_preview() -> None:
    preview = build_preview([], chunk_id=1)

    assert preview.chunks == []
    assert preview.total_chunks == 0
    assert preview.focused_chunk_id is None
    assert preview.truncated is False


def test_exactly_cap_is_not_truncated() -> None:
    rows = [_row(index, index) for index in range(1, MAX_PREVIEW_CHUNKS + 1)]

    preview = build_preview(rows)

    assert len(preview.chunks) == MAX_PREVIEW_CHUNKS
    assert preview.truncated is False
    assert preview.focused_chunk_id is None


def test_long_document_without_focus_returns_head_window() -> None:
    rows = [_row(index, index) for index in range(1, MAX_PREVIEW_CHUNKS + 51)]

    preview = build_preview(rows)

    assert [chunk.ord for chunk in preview.chunks[:1]] == [1]
    assert len(preview.chunks) == MAX_PREVIEW_CHUNKS
    assert preview.total_chunks == MAX_PREVIEW_CHUNKS + 50
    assert preview.truncated is True
