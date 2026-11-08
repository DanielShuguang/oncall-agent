"""解析与切分：标题路径、表格不切碎、DOCX/PDF 可读性。"""

from __future__ import annotations

import io

import pytest

try:
    from docx import Document
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ImportError:  # pragma: no cover - 解析器是 rag extra，未安装时整组跳过
    pytest.skip("需要 rag extra：uv sync --extra rag", allow_module_level=True)

from app.rag.chunk import chunk_parsed
from app.rag.parse import ParseError, parse_bytes
from app.rag.text import tokenize


def test_markdown_keeps_heading_path_and_table() -> None:
    content = """# 打印机指南

## 离线排查

先确认设备与电脑在同一网段。

### 步骤 3

重启 Print Spooler。

| 型号 | 端口 |
|---|---|
| HP-1020 | 9100 |
"""
    parsed = parse_bytes("printer.md", content.encode("utf-8"))
    assert parsed.title == "打印机指南"
    assert any(block.heading_path == "打印机指南 > 离线排查 > 步骤 3" for block in parsed.blocks)

    chunks = chunk_parsed(parsed)
    table_chunks = [chunk for chunk in chunks if chunk.is_table]
    assert len(table_chunks) == 1
    assert "| 型号 | 端口 |" in table_chunks[0].text
    assert "HP-1020" in table_chunks[0].text


def test_long_section_is_split_with_overlap() -> None:
    paragraph = "这是一段用于测试切分的排查步骤。" * 80
    markdown = f"# 长文档\n\n## 排查\n\n{paragraph}\n"
    parsed = parse_bytes("long.md", markdown.encode("utf-8"))
    chunks = chunk_parsed(parsed)

    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 650 for chunk in chunks)
    # 相邻切片应该有重叠，避免一句话被切断后两边都缺上下文
    assert chunks[0].text[-20:] in chunks[1].text


def test_docx_heading_path_and_table() -> None:
    document = Document()
    document.add_heading("网络指南", level=1)
    document.add_heading("VPN", level=2)
    document.add_paragraph("VPN 连不上时先检查客户端版本。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "错误码"
    table.cell(0, 1).text = "含义"
    table.cell(1, 0).text = "ERR-502"
    table.cell(1, 1).text = "认证失败"
    buffer = io.BytesIO()
    document.save(buffer)

    parsed = parse_bytes("network.docx", buffer.getvalue())
    assert any("网络指南 > VPN" in block.heading_path for block in parsed.blocks)
    assert any(block.is_table and "ERR-502" in block.text for block in parsed.blocks)


def test_pdf_without_text_layer_is_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(ParseError, match="文本层"):
        parse_bytes("scan.pdf", buffer.getvalue())


def _text_pdf(*page_texts: str) -> bytes:
    writer = PdfWriter()
    for text in page_texts:
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


def test_text_pdf_keeps_page_number_on_chunks() -> None:
    data = _text_pdf("VPN troubleshooting guide", "VPN client download steps")
    parsed = parse_bytes("vpn.pdf", data)
    assert parsed.page_count == 2
    assert any(block.page == 1 and "VPN troubleshooting" in block.text for block in parsed.blocks)
    assert any("第 1 页" in block.heading_path for block in parsed.blocks)

    # 页码必须跟着切片走：前端引用弹窗与 "跳到原文第几页" 都依赖它
    chunks = chunk_parsed(parsed)
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert all(chunk.heading for chunk in chunks)


def test_chunk_heading_falls_back_to_title() -> None:
    """纯文本没有标题层级时，引用 heading 不能是空串。"""
    parsed = parse_bytes("plain.txt", "第一行正文。\n\n第二行正文。".encode())
    chunks = chunk_parsed(parsed)
    assert chunks and all(chunk.heading == "plain" for chunk in chunks)


def test_unsupported_suffix_is_rejected() -> None:
    with pytest.raises(ParseError, match="不支持"):
        parse_bytes("setup.exe", b"binary")


def test_chinese_tokenizer_keeps_bigrams_and_drops_generic_words() -> None:
    tokens = tokenize("VPN 连不上，公司的规则是什么")
    assert "vpn" in tokens
    assert "连不" in tokens
    assert "不上" in tokens
    assert "公司" not in tokens
    assert "规则" not in tokens
    assert "什么" not in tokens
