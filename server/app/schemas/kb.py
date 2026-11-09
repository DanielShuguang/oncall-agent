"""知识库管理接口的响应模型（docs/03 §1、§5）。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.rag.types import DocumentInfo


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
    #: public（所有登录用户）/ roles（下列角色的交集），见 ADR-0019。
    #: 故意不给默认值：手工构造响应时漏掉可见性会直接报错，而不是静默显示成 public
    visibility: str
    allowed_roles: list[str]
    created_at: datetime

    @classmethod
    def from_document(cls, info: DocumentInfo) -> KbDocumentOut:
        """唯一映射点：漏字段会让「列表显示 public、实际是 roles」这种口径漂移。"""
        return cls(
            id=info.id,
            title=info.title,
            source=info.source,
            version=info.version,
            checksum=info.checksum,
            chunk_count=info.chunk_count,
            status=info.status,
            visibility=info.visibility,
            allowed_roles=list(info.allowed_roles),
            created_at=info.created_at,
        )


class KbAccessUpdateRequest(BaseModel):
    """`PATCH /admin/kb/documents/{id}/access`：整体替换可见范围。

    两项都必须显式给出：PATCH 是「把范围改成这样」，空 body / 只传一项
    都不应该被解释成某个默认值——尤其是不能把文档静默改成公开。
    """

    visibility: str
    allowed_roles: list[str]


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


class KbPreviewChunkOut(BaseModel):
    """引用跳全文返回的切片；带 `chunk_id` 才能在前端精确高亮引用段。"""

    chunk_id: int
    ord: int
    heading: str | None = None
    content: str
    page: int | None = None


class KbPreviewResponse(BaseModel):
    """`GET /kb/documents/{id}/preview`：全文按切片重组，`focused_chunk_id` 为空表示
    引用位置在当前窗口里找不到（文档已更新或引用过旧），前端只展示全文不滚动。"""

    document: KbDocumentOut
    chunks: list[KbPreviewChunkOut]
    focused_chunk_id: int | None = None
    total_chunks: int
    truncated: bool


class KbReindexResponse(BaseModel):
    chunks: int
