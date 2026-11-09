"""引用跳全文（W5 D24 收尾）。

与检索共用同一可见性边界：任何已登录员工都能打开答案引用过的文档全文。
理由是同一条 chat → retrieve → citation 链路本来就把切片正文交给了调用方，
多给上下文不构成新的授权边界（ADR-0018）。

刻意**不提供**列表/浏览接口：没有 `GET /kb/documents`，只能凭引用里的
`document_id` 打开，避免任何员工把知识库整库导出。管理接口（列表/上传/
重建索引）仍然要求管理员角色。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_identity
from app.api.errors import ApiError
from app.core.logging import get_logger
from app.rag.preview import build_preview
from app.rag.retrieve import KnowledgeBase
from app.rag.service import get_knowledge_base
from app.schemas.kb import KbDocumentOut, KbPreviewChunkOut, KbPreviewResponse
from app.tools.registry import Identity

router = APIRouter(prefix="/kb", tags=["kb"])
log = get_logger(__name__)


@router.get("/documents/{document_id}/preview")
async def preview_document(
    document_id: str,
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    _identity: Annotated[Identity, Depends(get_identity)],
    chunk_id: Annotated[int | None, Query(ge=1)] = None,
    ord: Annotated[int | None, Query(ge=1)] = None,
) -> KbPreviewResponse:
    try:
        result = await kb.get_document(document_id)
    except SQLAlchemyError as exc:
        log.error("kb_preview_failed", document_id=document_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "知识库暂不可用") from exc
    if result is None:
        raise ApiError(404, "NOT_FOUND", "文档不存在或已更新")

    info, rows = result
    preview = build_preview(rows, chunk_id=chunk_id, ord=ord)
    return KbPreviewResponse(
        document=KbDocumentOut(
            id=info.id,
            title=info.title,
            source=info.source,
            version=info.version,
            checksum=info.checksum,
            chunk_count=info.chunk_count,
            status=info.status,
            created_at=info.created_at,
        ),
        chunks=[
            KbPreviewChunkOut(
                chunk_id=item.chunk_id,
                ord=item.ord,
                heading=item.heading,
                content=item.content,
                page=item.page,
            )
            for item in preview.chunks
        ],
        focused_chunk_id=preview.focused_chunk_id,
        total_chunks=preview.total_chunks,
        truncated=preview.truncated,
    )
