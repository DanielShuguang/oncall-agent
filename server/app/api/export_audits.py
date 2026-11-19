"""CSV 导出下载审计（ADR-0094）。

六个业务导出端点（审批列表/统计、恢复审计列表/统计、置顶审计列表/统计）在 CSV
生成成功后调用 ``record_export``；审计写入失败时端点返回 503，不返回无法
留痕的下载。这里同时提供管理员只读列表与 CSV 导出，过滤按导出人/资源/UTC 日期；
导出审计列表自身也写一条 `export_audits` 记录（ADR-0096）。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.csv import csv_document
from app.core.logging import get_logger
from app.core.store import ExportAuditRecord, RunStore, get_store
from app.schemas.export_audit import ExportAuditListResponse, ExportAuditOut
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/export-audits", tags=["admin-export-audits"])
log = get_logger(__name__)

MAX_AUDIT_RANGE_DAYS = 365
MAX_CURSOR_LEN = 512
RESOURCE_PATTERN = (
    r"^(approvals|approval_stats|session_restores|session_restore_stats|"
    r"session_pins|session_pin_stats|export_audits)$"
)
MAX_EXPORT_ROWS = 5000
CSV_HEADERS = (
    "created_at",
    "user_id",
    "resource",
    "row_count",
    "truncated",
    "filters",
    "content_sha256",
)


async def record_export(
    store: RunStore,
    *,
    user_id: str,
    resource: str,
    filters: dict[str, str | None],
    row_count: int,
    truncated: bool = False,
    content: str | None = None,
) -> None:
    """记录一次成功生成的 CSV 导出；写失败直接 503（fail closed）。"""
    clean = {key: value for key, value in filters.items() if value}
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content is not None else None
    try:
        await store.record_export_audit(
            user_id=user_id,
            resource=resource,
            filters=clean,
            row_count=row_count,
            truncated=truncated,
            content_sha256=digest,
        )
    except SQLAlchemyError as exc:
        log.error("export_audit_write_failed", resource=resource, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "导出审计暂不可用") from exc


def _date_window(
    created_from: date | None, created_to: date | None
) -> tuple[datetime | None, datetime | None]:
    if created_from is None and created_to is None:
        return None, None
    if created_from is None or created_to is None:
        raise ApiError(422, "INVALID_RANGE", "created_from 和 created_to 必须同时提供")
    since = datetime.combine(created_from, time.min, tzinfo=UTC)
    until = datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=UTC)
    if until <= since:
        raise ApiError(422, "INVALID_RANGE", "created_to 不能早于 created_from")
    if (until - since).days > MAX_AUDIT_RANGE_DAYS:
        raise ApiError(422, "INVALID_RANGE", "日期范围不能超过 365 天")
    return since, until


def _fingerprint(
    user_id: str | None,
    resource: str | None,
    since: datetime | None,
    until: datetime | None,
) -> str:
    payload = json.dumps(
        {
            "user_id": user_id,
            "resource": resource,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _encode_cursor(record: ExportAuditRecord, fingerprint: str) -> str:
    payload = {
        "t": record.created_at.isoformat(),
        "i": record.audit_id,
        "f": fingerprint,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, fingerprint: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = datetime.fromisoformat(str(payload["t"]))
        audit_id = str(payload["i"])
        UUID(audit_id)
        if payload.get("f") != fingerprint:
            raise ValueError("filter mismatch")
    except (binascii.Error, KeyError, TypeError, ValueError) as exc:
        raise ApiError(400, "INVALID_CURSOR", "cursor 无效") from exc
    if created_at.tzinfo is None:
        raise ApiError(400, "INVALID_CURSOR", "cursor 无效")
    return created_at, audit_id


def _export_audits_csv(records: list[ExportAuditRecord]) -> str:
    return csv_document(
        CSV_HEADERS,
        (
            (
                record.created_at,
                record.user_id,
                record.resource,
                record.row_count,
                record.truncated,
                json.dumps(record.filters, ensure_ascii=False, sort_keys=True),
                record.content_sha256 or "",
            )
            for record in records
        ),
    )


@router.get("/export")
async def export_export_audits(
    store: Annotated[RunStore, Depends(get_store)],
    admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource: Annotated[str | None, Query(pattern=RESOURCE_PATTERN)] = None,
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
) -> Response:
    """导出导出审计 CSV；本导出自身也写审计（ADR-0096）。"""
    since, until = _date_window(created_from, created_to)
    try:
        records = await store.list_export_audits(
            user_id=user_id,
            resource=resource,
            created_after=since,
            created_before=until,
            limit=MAX_EXPORT_ROWS + 1,
        )
    except SQLAlchemyError as exc:
        log.error("export_audit_export_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "导出审计暂不可用") from exc
    truncated = len(records) > MAX_EXPORT_ROWS
    rows = records[:MAX_EXPORT_ROWS]
    content = _export_audits_csv(rows)
    await record_export(
        store,
        user_id=admin.user_id,
        resource="export_audits",
        filters={
            "user_id": user_id,
            "resource": resource,
            "created_from": created_from.isoformat() if created_from else None,
            "created_to": created_to.isoformat() if created_to else None,
        },
        row_count=len(rows),
        truncated=truncated,
        content=content,
    )
    filename = f"export-audits-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Export-Count": str(len(rows)),
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


@router.get("", response_model=ExportAuditListResponse)
async def list_export_audits(
    store: Annotated[RunStore, Depends(get_store)],
    _admin: Annotated[Identity, Depends(require_admin)],
    user_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource: Annotated[str | None, Query(pattern=RESOURCE_PATTERN)] = None,
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LEN)] = None,
) -> ExportAuditListResponse:
    since, until = _date_window(created_from, created_to)
    fingerprint = _fingerprint(user_id, resource, since, until)
    before = _decode_cursor(cursor, fingerprint) if cursor else None
    total: int | None = None
    if cursor is None:
        try:
            total = await store.count_export_audits(
                user_id=user_id,
                resource=resource,
                created_after=since,
                created_before=until,
            )
        except SQLAlchemyError as exc:
            log.error("export_audit_count_failed", error=str(exc))
            raise ApiError(503, "DATABASE_UNAVAILABLE", "导出审计暂不可用") from exc
    try:
        records = await store.list_export_audits(
            user_id=user_id,
            resource=resource,
            created_after=since,
            created_before=until,
            before=before,
            limit=limit + 1,
        )
    except SQLAlchemyError as exc:
        log.error("export_audit_list_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "导出审计暂不可用") from exc
    items = records[:limit]
    if total is not None and total < len(items):
        total = None
    next_cursor = None
    if len(records) > limit and items:
        next_cursor = _encode_cursor(items[-1], fingerprint)
    return ExportAuditListResponse(
        items=[
            ExportAuditOut(
                id=record.audit_id,
                user_id=record.user_id,
                resource=record.resource,
                filters=record.filters,
                row_count=record.row_count,
                truncated=record.truncated,
                content_sha256=record.content_sha256,
                created_at=record.created_at,
            )
            for record in items
        ],
        next_cursor=next_cursor,
        total=total,
    )
