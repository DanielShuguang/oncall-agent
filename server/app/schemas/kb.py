"""知识库管理接口的响应模型（docs/03 §1、§5）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KbChunkOut(BaseModel):
    """上传响应里的切片；`is_table` 来自本次切分结果，不落库。"""

    ord: int
    heading: str | None = None
    content: str
    page: int | None = None
    is_table: bool = False


class KbChunkPreviewOut(BaseModel):
    """详情预览只回可持久化的字段（表结构里没有 is_table，不能假装知道）。"""

    ord: int
    heading: str | None = None
    content: str
    page: int | None = None


class KbDocumentOut(BaseModel):
    id: str
    title: str
    source: str
    version: str | None = None
    checksum: str
    chunk_count: int
    status: str
    created_at: datetime


class KbUploadResponse(BaseModel):
    document: KbDocumentOut
    chunks: list[KbChunkOut]


class KbDocumentListResponse(BaseModel):
    documents: list[KbDocumentOut]
    total: int
    chunk_count: int


class KbDocumentDetailResponse(BaseModel):
    document: KbDocumentOut
    chunks: list[KbChunkPreviewOut]


class KbReindexResponse(BaseModel):
    chunks: int
