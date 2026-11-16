"""会话置顶审计的只读管理接口（ADR-0081/0082）。

- 只读：置顶/取消置顶仍走 `POST/DELETE /sessions/{id}/pin`，审计由 store 在
  状态变化事务内写
- 默认返回全部用户最近 50 条；`user_id`/`session_id`/`action` 可选过滤
- `(created_at, id)` 倒序 keyset 分页；游标绑定当前过滤条件，换过滤复用旧游标
  返回 400，避免静默跳到另一组结果
- 数据库不可用返回 503，不返回空列表冒充「没有置顶记录」
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.csv import csv_document
from app.core.logging import get_logger
from app.core.store import RunStore, SessionPinAuditRecord, get_store
from app.schemas.session import SessionPinAuditListResponse, SessionPinAuditOut
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/session-pins", tags=["admin-session-pins"])
log = get_logger(__name__)

MAX_EXPORT_ROWS = 5000
CSV_HEADERS = ("audit_id", "user_id", "session_id", "action", "created_at")


def _audits_csv(records: list[SessionPinAuditRecord]) -> str:
    return csv_document(
        CSV_HEADERS,
        (
            (
                record.audit_id,
                record.user_id,
                record.session_id,
                record.action,
                record.created_at,
            )
            for record in records
        ),
    )


def _out(record: SessionPinAuditRecord) -> SessionPinAuditOut:
    return SessionPinAuditOut(
        id=record.audit_id,
        user_id=record.user_id,
        session_id=record.session_id,
        action=record.action,
        created_at=record.created_at,
    )


def _cursor_error() -> ApiError:
    return ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取")


def _filter_fingerprint(
    *,
    user_id: str | None,
    session_id: str | None,
    action: str | None,
) -> str | None:
    """把过滤条件压成短指纹，避免把原始 id 塞进游标。"""
    if user_id is None and session_id is None and action is None:
        return None
    payload = json.dumps(
        {"u": user_id, "s": session_id, "a": action},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _encode_cursor(
    record: SessionPinAuditRecord,
    *,
    fingerprint: str | None,
) -> str:
    payload: dict[str, str] = {
        "t": record.created_at.isoformat(),
        "i": record.audit_id,
    }
    if fingerprint is not None:
        payload["f"] = fingerprint
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    fingerprint: str | None,
) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(data, dict):
            raise ValueError("cursor payload must be an object")
        expected = {"t", "i"}
        if fingerprint is not None:
            expected.add("f")
        if set(data) != expected:
            raise ValueError("cursor filters do not match")
        if fingerprint is not None and data.get("f") != fingerprint:
            raise ValueError("cursor filter fingerprint does not match")
        created_at = datetime.fromisoformat(str(data["t"]))
        if created_at.tzinfo is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        audit_id = str(UUID(str(data["i"])))
    except (ValueError, TypeError, KeyError, binascii.Error, json.JSONDecodeError) as exc:
        raise _cursor_error() from exc
    return created_at, audit_id


@router.get("/export")
async def export_session_pin_audits(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    action: Annotated[Literal["pin", "unpin"] | None, Query()] = None,
) -> Response:
    """导出置顶审计 CSV；过滤口径与列表一致，最多 5000 行（ADR-0084）。"""
    try:
        records = await store.list_session_pin_audits(
            user_id=user_id,
            session_id=session_id,
            action=action,
            limit=MAX_EXPORT_ROWS + 1,
        )
    except SQLAlchemyError as exc:
        log.warning("session_pin_audit_export_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "置顶审计暂不可用") from exc
    truncated = len(records) > MAX_EXPORT_ROWS
    rows = records[:MAX_EXPORT_ROWS]
    filename = f"session-pins-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
    return Response(
        content=_audits_csv(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Export-Count": str(len(rows)),
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


@router.get("", response_model=SessionPinAuditListResponse)
async def list_session_pin_audits(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    action: Annotated[Literal["pin", "unpin"] | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionPinAuditListResponse:
    """按 `(created_at, id)` 倒序返回置顶审计，可选用户/会话/动作过滤（ADR-0081/0082）。"""
    fingerprint = _filter_fingerprint(
        user_id=user_id,
        session_id=session_id,
        action=action,
    )
    before = (
        _decode_cursor(
            cursor,
            fingerprint=fingerprint,
        )
        if cursor is not None
        else None
    )
    try:
        records = await store.list_session_pin_audits(
            user_id=user_id,
            session_id=session_id,
            action=action,
            before=before,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        log.warning("session_pin_audit_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "置顶审计暂不可用") from exc
    return SessionPinAuditListResponse(
        items=[_out(record) for record in records],
        next_cursor=(
            _encode_cursor(
                records[-1],
                fingerprint=fingerprint,
            )
            if len(records) == limit
            else None
        ),
    )
