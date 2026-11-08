"""知识库管理接口的响应模型（docs/03 §1、§5）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KbChunkOut(BaseModel):
    ord: int
    heading: str | None = None
    content: str
    page: int | None = None
    is_table: bool = False


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
    chunks: list[KbChunkOut]


class KbReindexResponse(BaseModel):
    chunks: int
