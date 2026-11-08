"""文档解析：PDF / DOCX / Markdown / 纯文本 -> 带标题路径的块。

约束（docs/05-rag-design.md §3）：
- 统一产出 `ParsedDoc`，后续切分只认 blocks
- PDF 保留页码；DOCX 保留标题层级；MD/TXT 按 `#` 切
- 扫描版 PDF 没有文本层，v1 不做 OCR：直接报错，由上传接口返回 422
"""

from __future__ import annotations

import io
import statistics
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".md", ".markdown", ".txt"})


class ParseError(ValueError):
    """文件无法解析（格式不支持、扫描件、编码错误）。API 层转 422。"""


@dataclass(frozen=True, slots=True)
class Block:
    text: str
    heading_path: str
    page: int | None = None
    is_table: bool = False


@dataclass(slots=True)
class ParsedDoc:
    title: str
    blocks: list[Block] = field(default_factory=list)
    page_count: int | None = None

    @property
    def char_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)


def parse_bytes(filename: str, data: bytes) -> ParsedDoc:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ParseError(f"不支持的文件类型 {suffix or '(无扩展名)'}；支持 PDF/DOCX/MD/TXT")
    if not data:
        raise ParseError("文件为空")
    if suffix == ".pdf":
        return _parse_pdf(filename, data)
    if suffix == ".docx":
        return _parse_docx(filename, data)
    return _parse_text(filename, data)


def parse_markdown_text(text: str, *, title: str | None = None) -> ParsedDoc:
    """给 seed / 直接粘贴文本用：走与 .md 上传完全相同的解析路径。"""
    parsed = _parse_text("inline.md", text.encode("utf-8"))
    if title:
        parsed.title = title
    return parsed


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("文本编码无法识别（仅支持 UTF-8 / GB18030）")


def _strip_ext(filename: str) -> str:
    return Path(filename).stem or "未命名文档"


# ---------------------------------------------------------------------------
# Markdown / TXT
# ---------------------------------------------------------------------------


def _parse_text(filename: str, data: bytes) -> ParsedDoc:
    text = _decode(data)
    title = _strip_ext(filename)
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        content = "\n".join(paragraph).strip()
        paragraph.clear()
        if content:
            blocks.append(Block(text=content, heading_path=_heading_path(stack)))

    table_lines: list[str] = []

    def flush_table() -> None:
        if not table_lines:
            return
        content = "\n".join(table_lines).strip()
        table_lines.clear()
        if content:
            # 表格单独成 chunk 且保留表头（docs/05 §4）
            blocks.append(
                Block(text=content, heading_path=_heading_path(stack) or title, is_table=True)
            )

    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            paragraph.append(line)
            continue
        if not in_code and stripped.startswith("#"):
            flush()
            flush_table()
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped[level:].strip()
            if heading:
                stack = [(lvl, name) for lvl, name in stack if lvl < level]
                stack.append((level, heading))
                if level == 1 and title == _strip_ext(filename):
                    title = heading
            continue
        if not in_code and stripped.startswith("|"):
            flush()
            table_lines.append(line.rstrip())
            continue
        if table_lines:
            flush_table()
        if not stripped:
            flush()
            continue
        paragraph.append(line.rstrip())
    flush()
    flush_table()

    if not blocks:
        raise ParseError("文档没有可解析的正文")
    return ParsedDoc(title=title, blocks=blocks)


def _heading_path(stack: list[tuple[int, str]]) -> str:
    return " > ".join(name for _, name in stack)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _parse_docx(filename: str, data: bytes) -> ParsedDoc:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover - 仅在未安装 rag extra 时触发
        raise ParseError("未安装 python-docx，请执行 uv sync --extra rag") from exc

    document = Document(io.BytesIO(data))
    title = (document.core_properties.title or "").strip() or _strip_ext(filename)
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []

    def heading_level(paragraph: Paragraph) -> int | None:
        style = (paragraph.style.name or "") if paragraph.style is not None else ""
        if style.startswith("Heading "):
            try:
                return max(1, min(9, int(style.split(" ", 1)[1])))
            except ValueError:
                return None
        if style in {"Title", "Subtitle"}:
            return 1
        return None

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            level = heading_level(paragraph)
            if level is not None:
                stack = [(lvl, name) for lvl, name in stack if lvl < level]
                stack.append((level, text))
                if level == 1 and title == _strip_ext(filename):
                    title = text
                continue
            blocks.append(Block(text=text, heading_path=_heading_path(stack)))
        elif tag == "tbl":
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(
                    Block(
                        text="\n".join(rows),
                        heading_path=_heading_path(stack) or title,
                        is_table=True,
                    )
                )

    if not blocks:
        raise ParseError("DOCX 没有可解析的正文")
    return ParsedDoc(title=title, blocks=blocks)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _parse_pdf(filename: str, data: bytes) -> ParsedDoc:
    """优先 PyMuPDF（若环境里装了），否则用纯 Python 的 pypdf。

    PyMuPDF 2.x 的 wheel 带布局模型，体积 60MB+；私有化交付时不是必需。
    v0 只需要「可复制 PDF 的文本层 + 页码」，pypdf 足够且安装成本低。
    扫描件两种实现都读不出文本，统一 422（v1 不做 OCR）。
    """
    try:
        import pymupdf
    except ImportError:
        return _parse_pdf_pypdf(filename, data)

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError(f"PDF 打开失败: {exc}") from exc

    try:
        metadata_title = str((document.metadata or {}).get("title") or "").strip()
        title = metadata_title or _strip_ext(filename)
        blocks: list[Block] = []
        stack: list[tuple[int, str]] = []

        for page_index, page in enumerate(document, start=1):
            page_number = page_index
            # PDF 没有可靠的标题层级：每页重新开始，避免标题路径无限嵌套
            stack.clear()
            data_dict = page.get_text("dict")
            page_blocks = data_dict.get("blocks", [])
            sizes = [
                span.get("size", 0.0)
                for block in page_blocks
                if block.get("type") == 0
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text", "")).strip()
            ]
            median_size = statistics.median(sizes) if sizes else 10.0

            for block in page_blocks:
                if block.get("type") != 0:
                    continue
                lines: list[str] = []
                is_heading = False
                for line in block.get("lines", []):
                    spans = [span for span in line.get("spans", []) if str(span.get("text", ""))]
                    if not spans:
                        continue
                    text = "".join(str(span.get("text", "")) for span in spans).strip()
                    if not text:
                        continue
                    sizes = [float(span.get("size", 0.0)) for span in spans]
                    if sizes and max(sizes) >= median_size * 1.25 and len(text) <= 80:
                        is_heading = True
                    lines.append(text)
                content = "\n".join(lines).strip()
                if not content:
                    continue
                if is_heading:
                    stack.append((len(stack) + 1, content))
                    if len(stack) == 1 and title == _strip_ext(filename):
                        title = content
                    continue
                blocks.append(
                    Block(
                        text=content,
                        heading_path=_heading_path(stack) or title,
                        page=page_number,
                    )
                )

        if not blocks:
            raise ParseError("PDF 没有文本层（扫描件暂不支持 OCR），请上传可复制文字的版本")
        return ParsedDoc(title=title, blocks=blocks, page_count=document.page_count)
    finally:
        document.close()


def _parse_pdf_pypdf(filename: str, data: bytes) -> ParsedDoc:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 仅在未安装 rag extra 时触发
        raise ParseError("未安装 pypdf，请执行 uv sync --extra rag") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"PDF 打开失败: {exc}") from exc

    title = _strip_ext(filename)
    metadata_title = ""
    try:
        metadata = reader.metadata
        metadata_title = str(getattr(metadata, "title", "") or "").strip()
    except Exception:  # pragma: no cover - 损坏的元数据不该阻断解析
        metadata_title = ""
    if metadata_title:
        title = metadata_title

    blocks: list[Block] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # pragma: no cover - 单页坏文本不应让整份文档失败
            text = ""
        for paragraph in text.split("\n\n"):
            content = "\n".join(line.strip() for line in paragraph.splitlines()).strip()
            if len(content) < 10:
                continue
            blocks.append(
                Block(
                    text=content,
                    heading_path=f"{title} > 第 {page_number} 页",
                    page=page_number,
                )
            )

    if not blocks:
        raise ParseError("PDF 没有文本层（扫描件暂不支持 OCR），请上传可复制文字的版本")
    return ParsedDoc(title=title, blocks=blocks, page_count=len(reader.pages))
