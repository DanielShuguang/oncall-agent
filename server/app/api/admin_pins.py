"""会话置顶审计的只读管理接口（ADR-0081/0082/0087）。

- 只读：置顶/取消置顶仍走 `POST/DELETE /sessions/{id}/pin`，审计由 store 在
  状态变化事务内写
- 默认返回全部用户最近 50 条；`user_id`/`session_id`/`action` 可选过滤
- `(created_at, id)` 倒序 keyset 分页；游标绑定当前过滤条件，换过滤复用旧游标
  返回 400，避免静默跳到另一组结果
- `/stats` 给全局窗口汇总与 UTC 稀疏日趋势；不接列表过滤
- 数据库不可用返回 503，不返回空列表冒充「没有置顶记录」
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.csv import csv_document
from app.core.logging import get_logger
from app.core.store import RunStore, SessionPinAuditRecord, get_store
from app.schemas.session import (
    SessionPinAuditDayOut,
    SessionPinAuditListResponse,
    SessionPinAuditOut,
    SessionPinAuditStatsOut,
)
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/session-pins", tags=["admin-session-pins"])
log = get_logger(__name__)

MAX_EXPORT_ROWS = 5000
MAX_AUDIT_RANGE_DAYS = 365
CSV_HEADERS = ("audit_id", "user_id", "session_id", "action", "created_at")


def _created_window(
    created_from: date | None,
    created_to: date | None,
) -> tuple[datetime, datetime, str] | None:
    """把 UTC 自然日闭区间转成半开窗口，并校验两端/顺序/跨度（ADR-0086）。"""
    if created_from is None and created_to is None:
        return None
    if created_from is None or created_to is None:
        raise ApiError(422, "INVALID_RANGE", "created_from 与 created_to 需要同时提供")
    if created_to < created_from:
        raise ApiError(422, "INVALID_RANGE", "created_from 不能晚于 created_to")
    if created_to == date.max:
        raise ApiError(422, "INVALID_RANGE", "created_to 超出可查询范围")
    if (created_to - created_from).days + 1 > MAX_AUDIT_RANGE_DAYS:
        raise ApiError(
            422,
            "INVALID_RANGE",
            f"查询范围最多 {MAX_AUDIT_RANGE_DAYS} 天",
        )
    after = datetime.combine(created_from, time.min, tzinfo=UTC)
    before = datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=UTC)
    return after, before, f"{created_from.isoformat()}:{created_to.isoformat()}"


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
    created_range: str | None,
) -> str | None:
    """把过滤条件压成短指纹，避免把原始 id 塞进游标。"""
    if user_id is None and session_id is None and action is None and created_range is None:
        return None
    payload: dict[str, str | None] = {
        "u": user_id,
        "s": session_id,
        "a": action,
    }
    if created_range is not None:
        payload["d"] = created_range
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


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


@router.get("/stats", response_model=SessionPinAuditStatsOut)
async def get_session_pin_audit_stats(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> SessionPinAuditStatsOut:
    """全局置顶/取消置顶审计的窗口统计（ADR-0087）。"""
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    try:
        stats = await store.session_pin_audit_stats(since=since, until=until)
    except SQLAlchemyError as exc:
        log.warning("session_pin_audit_stats_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "置顶审计统计暂不可用") from exc
    return SessionPinAuditStatsOut(
        days=days,
        since=stats.since,
        until=stats.until,
        pins=stats.pins,
        unpins=stats.unpins,
        users=stats.users,
        sessions=stats.sessions,
        daily=[
            SessionPinAuditDayOut(day=day.day, pins=day.pins, unpins=day.unpins)
            for day in stats.daily
        ],
    )


@router.get("/export")
async def export_session_pin_audits(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    action: Annotated[Literal["pin", "unpin"] | None, Query()] = None,
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
) -> Response:
    """导出置顶审计 CSV；过滤口径与列表一致，最多 5000 行（ADR-0084/0086）。"""
    window = _created_window(created_from, created_to)
    try:
        records = await store.list_session_pin_audits(
            user_id=user_id,
            session_id=session_id,
            action=action,
            created_after=window[0] if window else None,
            created_before=window[1] if window else None,
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
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionPinAuditListResponse:
    """按 `(created_at, id)` 倒序返回置顶审计，可选用户/会话/动作/日期过滤。

    ADR-0081/0082/0086。
    """
    window = _created_window(created_from, created_to)
    fingerprint = _filter_fingerprint(
        user_id=user_id,
        session_id=session_id,
        action=action,
        created_range=window[2] if window else None,
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
            created_after=window[0] if window else None,
            created_before=window[1] if window else None,
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
