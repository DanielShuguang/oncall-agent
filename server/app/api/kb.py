"""引用跳全文（W5 D24 收尾，可见性见 ADR-0019）。

可见性与检索**同一条规则**：`public` 文档所有登录用户可读；`roles` 文档要求
角色交集；`admin`（知识库所有者）不受限。不可见与不存在都返回 404 ——
403 会泄露「这篇文档存在但你不能看」，而 `document_id` 本来就是 UUID。

刻意**不提供**列表/浏览接口：没有 `GET /kb/documents`，调用方只能凭已知的
`document_id` 打开，避免员工浏览或导出整库。接口不校验该 id 是否真的出现在
调用方的引用里（那需要绑定 run 归属），靠「无列表 + UUID 不可猜」收敛；
管理接口（列表/上传/改可见范围/重建索引）仍然要求管理员角色。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_viewer
from app.api.errors import ApiError
from app.core.logging import get_logger
from app.rag.access import Viewer
from app.rag.preview import build_preview
from app.rag.retrieve import KnowledgeBase
from app.rag.service import get_knowledge_base
from app.schemas.kb import KbDocumentOut, KbPreviewChunkOut, KbPreviewResponse

router = APIRouter(prefix="/kb", tags=["kb"])
log = get_logger(__name__)


@router.get("/documents/{document_id}/preview")
async def preview_document(
    document_id: str,
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    viewer: Annotated[Viewer, Depends(get_viewer)],
    chunk_id: Annotated[int | None, Query(ge=1)] = None,
    ord: Annotated[int | None, Query(ge=1)] = None,
) -> KbPreviewResponse:
    try:
        result = await kb.get_document(document_id, viewer=viewer)
    except SQLAlchemyError as exc:
        log.error("kb_preview_failed", document_id=document_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "知识库暂不可用") from exc
    if result is None:
        raise ApiError(404, "NOT_FOUND", "文档不存在或已更新")

    info, rows = result
    preview = build_preview(rows, chunk_id=chunk_id, ord=ord)
    return KbPreviewResponse(
        document=KbDocumentOut.from_document(info),
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
