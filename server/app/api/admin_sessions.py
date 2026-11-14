"""会话恢复审计的只读管理接口（ADR-0059/0060/0061）。

- 只读：恢复动作仍走 `POST /sessions/hidden/restore`，审计由 store 在删除事务内写
- 默认返回全部用户最近 50 条；`user_id`/`session_id` 可选过滤
- `(restored_at, id)` 倒序 keyset 分页；游标绑定当前过滤条件，换条件返回 400
- 不提供导出：审计表按 365 天保留
- 数据库不可用返回 503，不返回空列表冒充「没有恢复记录」
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
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


def _cursor_error() -> ApiError:
    return ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取")


def _encode_cursor(
    record: SessionRestoreAuditRecord, user_id: str | None, session_id: str | None
) -> str:
    """游标绑定本次的 `user_id`/`session_id` 过滤；否则换条件会翻到错误位置。"""
    payload = {
        "t": record.restored_at.isoformat(),
        "i": record.audit_id,
        "u": user_id,
        "s": session_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str, user_id: str | None, session_id: str | None
) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + padding))
        # ADR-0060 的旧游标没有 `s`；把它当作「没有 session 过滤」继续兼容
        if not isinstance(data, dict) or not {"t", "i", "u"} <= set(data) <= {"t", "i", "u", "s"}:
            raise ValueError("unexpected cursor shape")
        if data["u"] != user_id or data.get("s") != session_id:
            raise ValueError("cursor filter mismatch")
        restored_at = datetime.fromisoformat(str(data["t"]))
        if restored_at.tzinfo is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        # UUID 字符串大小写/urn 形式都合法；归一化后内存与 PG 的排序才一致
        audit_id = str(uuid.UUID(str(data["i"])))
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise _cursor_error() from None
    return restored_at, audit_id


@router.get("")
async def list_session_restores(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionRestoreAuditListResponse:
    before = _decode_cursor(cursor, user_id, session_id) if cursor is not None else None
    try:
        records = await store.list_session_restore_audits(
            user_id=user_id, session_id=session_id, before=before, limit=limit
        )
    except SQLAlchemyError as exc:
        log.error("session_restore_audit_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "会话恢复审计暂不可用") from exc
    next_cursor = (
        _encode_cursor(records[-1], user_id, session_id) if len(records) == limit else None
    )
    return SessionRestoreAuditListResponse(
        items=[_out(record) for record in records], next_cursor=next_cursor
    )
