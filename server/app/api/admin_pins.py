"""会话置顶审计的只读管理接口（ADR-0081）。

- 只读：置顶/取消置顶仍走 `POST/DELETE /sessions/{id}/pin`，审计由 store 在
  状态变化事务内写
- 默认返回全部用户最近 50 条；`user_id`/`session_id`/`action` 可选过滤
- 暂不分页；审计量小，先给有界最近 N 条
- 数据库不可用返回 503，不返回空列表冒充「没有置顶记录」
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.logging import get_logger
from app.core.store import RunStore, SessionPinAuditRecord, get_store
from app.schemas.session import SessionPinAuditListResponse, SessionPinAuditOut
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/session-pins", tags=["admin-session-pins"])
log = get_logger(__name__)


def _out(record: SessionPinAuditRecord) -> SessionPinAuditOut:
    return SessionPinAuditOut(
        id=record.audit_id,
        user_id=record.user_id,
        session_id=record.session_id,
        action=record.action,
        created_at=record.created_at,
    )


@router.get("", response_model=SessionPinAuditListResponse)
async def list_session_pin_audits(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    action: Annotated[Literal["pin", "unpin"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionPinAuditListResponse:
    """按 `created_at` 倒序返回置顶审计，可选用户/会话/动作过滤（ADR-0081）。"""
    try:
        records = await store.list_session_pin_audits(
            user_id=user_id,
            session_id=session_id,
            action=action,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        log.warning("session_pin_audit_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "置顶审计暂不可用") from exc
    return SessionPinAuditListResponse(items=[_out(record) for record in records])
