"""回答引用快照的清洗与上限（ADR-0031）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.store import (
    MAX_CITATION_SNIPPET,
    MAX_CITATION_TITLE,
    MAX_CITED_DOCUMENTS,
    EventType,
    build_run_patch,
)


def _snapshot(citations: Any) -> list[dict[str, Any]] | None:
    patch = build_run_patch(
        EventType.MESSAGE_COMPLETED,
        {"text": "回答", "citations": citations},
        datetime.now(UTC),
    )
    return patch.citations


def test_citation_snapshot_clips_text_and_skips_invalid_items() -> None:
    long_title = "标" * (MAX_CITATION_TITLE + 20)
    long_snippet = "片" * (MAX_CITATION_SNIPPET + 20)
    snapshot = _snapshot(
        [
            {
                "chunk_id": "7",
                "document_id": "doc_1",
                "ord": True,
                "title": long_title,
                "heading": long_title,
                "snippet": long_snippet,
                "page": True,
            },
            {"document_id": "", "title": "空 id 不能预览"},
            {"document_id": "doc_2", "title": None, "snippet": None, "page": 4},
            "not-a-dict",
        ]
    )

    assert snapshot == [
        {
            "chunk_id": 0,
            "document_id": "doc_1",
            "ord": 0,
            "title": long_title[:MAX_CITATION_TITLE],
            "snippet": long_snippet[:MAX_CITATION_SNIPPET],
            "heading": long_title[:MAX_CITATION_TITLE],
        },
        {
            "chunk_id": 0,
            "document_id": "doc_2",
            "ord": 0,
            "title": "",
            "snippet": "",
            "page": 4,
        },
    ]


def test_citation_snapshot_distinguishes_empty_and_caps_count() -> None:
    assert _snapshot([]) == []
    assert _snapshot(None) is None
    assert _snapshot("not-a-list") is None

    many = [{"document_id": f"doc_{i}", "title": f"t{i}"} for i in range(MAX_CITED_DOCUMENTS + 5)]
    snapshot = _snapshot(many)
    assert snapshot is not None
    assert len(snapshot) == MAX_CITED_DOCUMENTS
    assert snapshot[0]["document_id"] == "doc_0"
    assert snapshot[-1]["document_id"] == f"doc_{MAX_CITED_DOCUMENTS - 1}"
