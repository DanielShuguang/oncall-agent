"""会话恢复审计的只读管理接口（ADR-0059/0060/0061/0062/0064/0065/0066/0067）。

- 只读：恢复动作仍走 `POST /sessions/hidden/restore`，审计由 store 在删除事务内写
- 默认返回全部用户最近 50 条；`user_id`/`session_id` 可选过滤
- `(restored_at, id)` 倒序 keyset 分页；游标绑定当前过滤条件，换条件返回 400
- 第一页附带同过滤条件总数；后续页为 null（ADR-0064）
- CSV 导出：有上限的同步导出，超上限截断并显式告知
- 统计：窗口内恢复次数、用户数、会话数与 UTC 日趋势（ADR-0065）
- 列表/导出/统计可传 UTC 自然日闭区间 `restored_from`/`restored_to`（ADR-0067）
- 数据库不可用返回 503，不返回空列表冒充「没有恢复记录」
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.csv import csv_document
from app.core.logging import get_logger
from app.core.store import RunStore, SessionRestoreAuditRecord, get_store
from app.schemas.session import (
    SessionRestoreAuditDayOut,
    SessionRestoreAuditListResponse,
    SessionRestoreAuditOut,
    SessionRestoreAuditStatsOut,
)
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/session-restores", tags=["admin-session-restores"])
log = get_logger(__name__)

#: 同步导出必须有上限；超过上限只导出当前排序的前 N 条并显式告知截断（ADR-0062）。
MAX_EXPORT_ROWS = 5000
CSV_HEADERS = (
    "audit_id",
    "user_id",
    "restored_at",
    "requested_count",
    "restored_count",
    "session_ids",
)
#: 审计默认保留 365 天，日期范围最多覆盖同样长的窗口（ADR-0067）。
MAX_AUDIT_RANGE_DAYS = 365


def _audit_date_window(
    restored_from: date | None, restored_to: date | None
) -> tuple[datetime, datetime, str] | None:
    """把 UTC 自然日闭区间换算成时间窗口，并生成游标绑定键（ADR-0067）。

    两端必须同时提供；不提供时返回 None，保持原有「最近 N 天」或全量行为。
    """
    if (restored_from is None) != (restored_to is None):
        raise ApiError(422, "INVALID_RANGE", "restored_from 与 restored_to 必须同时提供")
    if restored_from is None:
        return None
    assert restored_to is not None
    if restored_to < restored_from:
        raise ApiError(422, "INVALID_RANGE", "restored_from 不能晚于 restored_to")
    span = (restored_to - restored_from).days + 1
    if span > MAX_AUDIT_RANGE_DAYS:
        raise ApiError(422, "INVALID_RANGE", "日期范围不能超过 365 天")
    since = datetime.combine(restored_from, time.min, tzinfo=UTC)
    until = datetime.combine(restored_to, time.max, tzinfo=UTC)
    return since, until, f"{restored_from.isoformat()}:{restored_to.isoformat()}"


def _out(record: SessionRestoreAuditRecord) -> SessionRestoreAuditOut:
    return SessionRestoreAuditOut(
        id=record.audit_id,
        user_id=record.user_id,
        session_ids=list(record.session_ids),
        requested_count=record.requested_count,
        restored_count=record.restored_count,
        restored_at=record.restored_at,
    )


def _audits_csv(records: list[SessionRestoreAuditRecord]) -> str:
    """导出审计元数据；`session_ids` 用 JSON 数组保留原顺序。"""
    return csv_document(
        CSV_HEADERS,
        (
            (
                record.audit_id,
                record.user_id,
                record.restored_at,
                record.requested_count,
                record.restored_count,
                json.dumps(list(record.session_ids), ensure_ascii=False, separators=(",", ":")),
            )
            for record in records
        ),
    )


def _cursor_error() -> ApiError:
    return ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取")


def _encode_cursor(
    record: SessionRestoreAuditRecord,
    user_id: str | None,
    session_id: str | None,
    date_key: str | None,
) -> str:
    """游标绑定本次的 `user_id`/`session_id`/日期范围；否则换条件会翻错位置。"""
    payload = {
        "t": record.restored_at.isoformat(),
        "i": record.audit_id,
        "u": user_id,
    }
    # 无过滤时保持旧形状：滚动升级期间旧实例仍能解析新实例返回的游标。
    if session_id is not None:
        payload["s"] = session_id
    if date_key is not None:
        payload["d"] = date_key
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str, user_id: str | None, session_id: str | None, date_key: str | None
) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + padding))
        expected = {"t", "i", "u"}
        if session_id is not None:
            expected.add("s")
        if date_key is not None:
            expected.add("d")
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError("unexpected cursor shape")
        if data["u"] != user_id or data.get("s") != session_id or data.get("d") != date_key:
            raise ValueError("cursor filter mismatch")
        restored_at = datetime.fromisoformat(str(data["t"]))
        if restored_at.tzinfo is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        # UUID 字符串大小写/urn 形式都合法；归一化后内存与 PG 的排序才一致
        audit_id = str(uuid.UUID(str(data["i"])))
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise _cursor_error() from None
    return restored_at, audit_id


@router.get("/stats", response_model=SessionRestoreAuditStatsOut)
async def session_restore_stats(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    days: Annotated[int | None, Query(ge=1, le=365)] = None,
    restored_from: Annotated[date | None, Query()] = None,
    restored_to: Annotated[date | None, Query()] = None,
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> SessionRestoreAuditStatsOut:
    """窗口内恢复活动汇总（ADR-0065/0066/0067）；日期范围与 `days` 二选一。"""
    window = _audit_date_window(restored_from, restored_to)
    if window is None:
        selected_days = days or 30
        until = datetime.now(UTC)
        since = until - timedelta(days=selected_days)
        days_out = selected_days
    else:
        if days is not None:
            raise ApiError(422, "INVALID_RANGE", "days 与 restored_from/restored_to 不能同时使用")
        since, until, _ = window
        days_out = (until.date() - since.date()).days + 1
    try:
        stats = await store.session_restore_audit_stats(
            since=since,
            until=until,
            user_id=user_id,
            session_id=session_id,
        )
    except SQLAlchemyError as exc:
        log.error("session_restore_audit_stats_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "会话恢复审计暂不可用") from exc
    return SessionRestoreAuditStatsOut(
        days=days_out,
        since=stats.since,
        until=stats.until,
        restores=stats.restores,
        users=stats.users,
        sessions=stats.sessions,
        daily=[
            SessionRestoreAuditDayOut(day=day.day, restores=day.restores, sessions=day.sessions)
            for day in stats.daily
        ],
    )


@router.get("/export")
async def export_session_restores(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    restored_from: Annotated[date | None, Query()] = None,
    restored_to: Annotated[date | None, Query()] = None,
) -> Response:
    """按当前过滤导出审计 CSV（ADR-0062/0067）；超上限截断，不做异步导出任务。"""
    window = _audit_date_window(restored_from, restored_to)
    try:
        records = await store.list_session_restore_audits(
            user_id=user_id,
            session_id=session_id,
            restored_from=window[0] if window is not None else None,
            restored_to=window[1] if window is not None else None,
            limit=MAX_EXPORT_ROWS + 1,
        )
    except SQLAlchemyError as exc:
        log.error("session_restore_audit_export_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "会话恢复审计暂不可用") from exc
    truncated = len(records) > MAX_EXPORT_ROWS
    rows = records[:MAX_EXPORT_ROWS]
    filename = f"session-restores-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
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


@router.get("")
async def list_session_restores(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    restored_from: Annotated[date | None, Query()] = None,
    restored_to: Annotated[date | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionRestoreAuditListResponse:
    """按 `(restored_at, id)` 倒序分页；第一页附带同过滤条件总数（ADR-0064/0067）。"""
    window = _audit_date_window(restored_from, restored_to)
    restored_from_at = window[0] if window is not None else None
    restored_to_at = window[1] if window is not None else None
    date_key = window[2] if window is not None else None
    before = _decode_cursor(cursor, user_id, session_id, date_key) if cursor is not None else None
    try:
        records = await store.list_session_restore_audits(
            user_id=user_id,
            session_id=session_id,
            restored_from=restored_from_at,
            restored_to=restored_to_at,
            before=before,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        log.error("session_restore_audit_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "会话恢复审计暂不可用") from exc
    total: int | None = None
    if cursor is None:
        # 只给第一页；后续页不再 COUNT，避免每次「加载更多」多一次全表扫描
        try:
            total = await store.count_session_restore_audits(
                user_id=user_id,
                session_id=session_id,
                restored_from=restored_from_at,
                restored_to=restored_to_at,
            )
        except SQLAlchemyError as exc:
            log.error("session_restore_audit_count_failed", error=str(exc))
            raise ApiError(503, "DATABASE_UNAVAILABLE", "会话恢复审计暂不可用") from exc
    next_cursor = (
        _encode_cursor(records[-1], user_id, session_id, date_key)
        if len(records) == limit
        else None
    )
    return SessionRestoreAuditListResponse(
        items=[_out(record) for record in records], next_cursor=next_cursor, total=total
    )
