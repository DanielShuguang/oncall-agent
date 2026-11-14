"""会话恢复审计的只读管理接口（ADR-0059）。

- 只读：恢复动作仍走 `POST /sessions/hidden/restore`，审计由 store 在删除事务内写
- 默认返回全部用户最近 50 条；`user_id` 可选过滤
- 不提供分页/导出：审计表按 365 天保留，管理页先看最近记录
- 数据库不可用返回 503，不返回空列表冒充「没有恢复记录」
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.logging import get_logger
from app.core.store import RunStore, SessionRestoreAuditRecord, get_store
from app.schemas.session import SessionRestoreAuditListResponse, SessionRestoreAuditOut
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/session-restores", tags=["admin-session-restores"])
log = get_logger(__name__)


def _out(record: SessionRestoreAuditRecord) -> SessionRestoreAuditOut:
    return SessionRestoreAuditOut(
        id=record.audit_id,
        user_id=record.user_id,
        session_ids=list(record.session_ids),
        requested_count=record.requested_count,
        restored_count=record.restored_count,
        restored_at=record.restored_at,
    )


@router.get("")
async def list_session_restores(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionRestoreAuditListResponse:
    try:
        records = await store.list_session_restore_audits(user_id=user_id, limit=limit)
    except SQLAlchemyError as exc:
        log.error("session_restore_audit_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "会话恢复审计暂不可用") from exc
    return SessionRestoreAuditListResponse(items=[_out(record) for record in records])
