"""CSV 导出下载审计的响应模型（ADR-0094）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ExportAuditOut(BaseModel):
    id: str
    user_id: str
    resource: str
    filters: dict[str, str]
    row_count: int
    truncated: bool
    content_sha256: str | None
    created_at: datetime


class ExportAuditListResponse(BaseModel):
    items: list[ExportAuditOut]
    next_cursor: str | None
    total: int | None
