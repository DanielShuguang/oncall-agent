"""CSV 导出的小工具：UTF-8 BOM、CRLF 与公式注入防护。

审批与审计导出共用同一套单元格规则，避免两处安全处理漂移（ADR-0056/0062）。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import datetime


def csv_cell(value: object) -> str:
    """CSV 单元格：日期用 ISO 8601，并挡住 Excel 公式注入。"""
    if value is None:
        text = ""
    elif isinstance(value, datetime):
        text = value.isoformat()
    else:
        text = str(value)
    # Excel/WPS 会把以这些字符开头的单元格当公式；前置单引号让它按文本显示。
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def csv_document(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """生成带 BOM 与 CRLF 的 CSV 文本；调用方负责行数上限。"""
    buffer = io.StringIO()
    buffer.write("\ufeff")  # Excel 识别 UTF-8
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_cell(cell) for cell in row])
    return buffer.getvalue()
