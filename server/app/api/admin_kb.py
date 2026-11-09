"""知识库管理接口（W2 D7/D8）。

- 上传：解析 -> 结构切分 -> 向量化 -> 入库；返回 chunks 与 heading_path
- 重建索引：用当前 embedder 重算全部切片向量（换模型时用）
- 列表/详情：给 W5 D21 的知识库管理页预留最小读接口

管理接口要求 `ONCALL_ADMIN_ROLES` 中的角色（默认 `admin`）。
权限矩阵在 W3 D12 落到数据库，这里先做入口保护。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.access import Viewer, parse_access
from app.rag.chunk import Chunk
from app.rag.embed import EmbeddingError
from app.rag.parse import ParseError
from app.rag.retrieve import KnowledgeBase
from app.rag.service import get_knowledge_base
from app.schemas.kb import (
    KbAccessUpdateRequest,
    KbChunkOut,
    KbChunkPreviewOut,
    KbDocumentDetailResponse,
    KbDocumentListResponse,
    KbDocumentOut,
    KbReindexResponse,
    KbUploadResponse,
)
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/kb", tags=["admin-kb"])
log = get_logger(__name__)


def _chunk_out(chunk: Chunk) -> KbChunkOut:
    return KbChunkOut(
        ord=chunk.ord,
        heading=chunk.heading,
        content=chunk.text,
        page=chunk.page,
        is_table=chunk.is_table,
    )


@router.post("/documents", status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF / DOCX / MD / TXT")],
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    _admin: Annotated[Identity, Depends(require_admin)],
    visibility: Annotated[str, Form(description="public / roles")] = "public",
    allowed_roles: Annotated[str, Form(description="逗号分隔的角色，如 hr,finance")] = "",
) -> KbUploadResponse:
    settings = get_settings()
    filename = Path(file.filename or "upload.md").name
    try:
        scope, roles = parse_access(visibility, allowed_roles)
    except ValueError as exc:
        raise ApiError(422, "INVALID_ARGS", str(exc)) from exc
    max_bytes = settings.kb_max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ApiError(
            413,
            "FILE_TOO_LARGE",
            f"文件超过 {settings.kb_max_upload_mb}MB 上限",
        )
    try:
        info, chunks = await kb.index_bytes(filename, data, visibility=scope, allowed_roles=roles)
    except ParseError as exc:
        raise ApiError(422, "PARSE_FAILED", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(422, "PARSE_FAILED", str(exc)) from exc
    except EmbeddingError as exc:
        raise ApiError(503, "EMBEDDING_FAILED", str(exc)) from exc
    except SQLAlchemyError as exc:
        log.error("kb_index_failed", source=filename, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "知识库写入失败，请稍后重试") from exc
    log.info(
        "kb_document_indexed",
        document_id=info.id,
        source=filename,
        chunks=info.chunk_count,
        visibility=info.visibility,
        allowed_roles=list(info.allowed_roles),
    )
    return KbUploadResponse(
        document=KbDocumentOut.from_document(info),
        chunks=[_chunk_out(chunk) for chunk in chunks[:50]],
    )


@router.get("/documents")
async def list_documents(
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    _admin: Annotated[Identity, Depends(require_admin)],
) -> KbDocumentListResponse:
    try:
        documents = await kb.list_documents()
        chunks = await kb.chunk_count()
    except SQLAlchemyError as exc:
        log.error("kb_list_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "知识库暂不可用") from exc
    return KbDocumentListResponse(
        documents=[KbDocumentOut.from_document(info) for info in documents],
        total=len(documents),
        chunk_count=chunks,
    )


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    _admin: Annotated[Identity, Depends(require_admin)],
    preview: Annotated[int, Query(ge=1, le=200)] = 20,
) -> KbDocumentDetailResponse:
    try:
        # 管理接口在 require_admin 之后：按知识库所有者读，不再做文档级过滤
        result = await kb.get_document(document_id, viewer=Viewer(unrestricted=True))
    except SQLAlchemyError as exc:
        log.error("kb_document_failed", document_id=document_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "知识库暂不可用") from exc
    if result is None:
        raise ApiError(404, "NOT_FOUND", "文档不存在")
    info, rows = result
    return KbDocumentDetailResponse(
        document=KbDocumentOut.from_document(info),
        chunks=[
            KbChunkPreviewOut(
                ord=row.ord,
                heading=row.heading,
                content=row.content,
                page=row.page,
            )
            for row in rows[:preview]
        ],
    )


@router.patch("/documents/{document_id}/access")
async def update_document_access(
    document_id: str,
    body: KbAccessUpdateRequest,
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    admin: Annotated[Identity, Depends(require_admin)],
) -> KbDocumentOut:
    """只改可见范围；不重新切分，`chunk_id` 保持不变，已有引用继续可用。"""
    try:
        visibility, roles = parse_access(body.visibility, body.allowed_roles)
    except ValueError as exc:
        raise ApiError(422, "INVALID_ARGS", str(exc)) from exc
    try:
        info = await kb.set_access(document_id, visibility=visibility, allowed_roles=roles)
    except SQLAlchemyError as exc:
        log.error("kb_access_update_failed", document_id=document_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "可见范围保存失败，请稍后重试") from exc
    if info is None:
        raise ApiError(404, "NOT_FOUND", "文档不存在")
    log.info(
        "kb_document_access_updated",
        document_id=document_id,
        visibility=info.visibility,
        allowed_roles=list(info.allowed_roles),
        by=admin.user_id,
    )
    return KbDocumentOut.from_document(info)


@router.post("/reindex")
async def reindex(
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    _admin: Annotated[Identity, Depends(require_admin)],
) -> KbReindexResponse:
    try:
        count = await kb.reindex()
    except EmbeddingError as exc:
        raise ApiError(503, "EMBEDDING_FAILED", str(exc)) from exc
    except SQLAlchemyError as exc:
        log.error("kb_reindex_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "重建索引失败，请稍后重试") from exc
    log.info("kb_reindexed", chunks=count)
    return KbReindexResponse(chunks=count)
