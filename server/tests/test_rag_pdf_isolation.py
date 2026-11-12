"""PDF 解析的子进程隔离（ADR-0032）。"""

from __future__ import annotations

import io

import pytest

pypdf = pytest.importorskip("pypdf")

from pypdf.generic import (  # noqa: E402 - importorskip 之后再导入
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.rag.parse import ParseError, parse_bytes  # noqa: E402
from app.rag.pdf_isolation import parse_pdf_isolated  # noqa: E402


def _text_pdf(text: str) -> bytes:
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 72 200 Td (" + text.encode("ascii") + b") Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_text_pdf_is_parsed_in_subprocess() -> None:
    parsed = parse_bytes("vpn.pdf", _text_pdf("VPN troubleshooting guide"))

    assert parsed.page_count == 1
    assert any("VPN troubleshooting" in block.text for block in parsed.blocks)


def test_invalid_pdf_error_crosses_process_boundary() -> None:
    with pytest.raises(ParseError, match="PDF 打开失败"):
        parse_bytes("broken.pdf", b"this is not a pdf")


def test_pdf_parse_timeout_is_reported() -> None:
    with pytest.raises(ParseError, match="PDF 解析超时"):
        parse_pdf_isolated("slow.pdf", b"%PDF-1.4\n", timeout_s=0.01)
