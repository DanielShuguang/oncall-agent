"""审批接口（W3 D14）。

契约见 docs/03 §4：
- 只有审批人角色能决议，且不能审批自己发起的操作
- 幂等：重复 resolve 返回首次结果，不重复执行写工具
- 过期：超过 expires_at 置 expired，run 转 failed(APPROVAL_TIMEOUT)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_approval_service, get_identity
from app.api.errors import ApiError
from app.approvals.service import ApprovalService, approval_payload
from app.approvals.types import (
    ApprovalForbidden,
    ApprovalGroupBy,
    ApprovalListCursor,
    ApprovalListFilters,
    ApprovalNotFound,
    ApprovalNotReady,
    ApprovalRecord,
    ApprovalScopeUnsupported,
    PendingApprovalCursor,
    ResolvedApprovalCursor,
)
from app.core.logging import get_logger
from app.core.store import RunStore, get_store
from app.schemas.approval import (
    ApprovalDayStatsOut,
    ApprovalGroupStatsOut,
    ApprovalListResponse,
    ApprovalOut,
    ApprovalResolveRequest,
    ApprovalResolveResponse,
    ApprovalStatsResponse,
)
from app.tools.registry import Identity

router = APIRouter(tags=["approvals"])
log = get_logger(__name__)


def _cursor_error() -> ApiError:
    return ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取")


def _approval_filters(
    status: str,
    *,
    tool: str | None,
    resolved_by: str | None,
    resolved_from: date | None,
    resolved_to: date | None,
) -> ApprovalListFilters:
    """把查询参数收敛成存储层筛选条件（ADR-0054）。"""
    if status == "pending" and any(
        value is not None for value in (tool, resolved_by, resolved_from, resolved_to)
    ):
        raise ApiError(422, "INVALID_FILTER", "待办列表不支持已办筛选")
    tool_name = tool.strip() if tool is not None else None
    approver = resolved_by.strip() if resolved_by is not None else None
    if tool is not None and not tool_name:
        raise ApiError(422, "INVALID_FILTER", "tool 不能为空")
    if resolved_by is not None and not approver:
        raise ApiError(422, "INVALID_FILTER", "resolved_by 不能为空")
    if resolved_from is not None and resolved_to is not None and resolved_from > resolved_to:
        raise ApiError(422, "INVALID_RANGE", "resolved_from 不能晚于 resolved_to")
    if resolved_to == date.max:
        raise ApiError(422, "INVALID_RANGE", "resolved_to 超出可表示范围")
    start = (
        datetime.combine(resolved_from, time.min, tzinfo=UTC) if resolved_from is not None else None
    )
    end = (
        datetime.combine(resolved_to + timedelta(days=1), time.min, tzinfo=UTC)
        if resolved_to is not None
        else None
    )
    return ApprovalListFilters(
        tool_name=tool_name,
        resolved_by=approver,
        resolved_from=start,
        resolved_to=end,
    )


def _filter_fingerprint(filters: ApprovalListFilters) -> str | None:
    """游标绑定筛选条件：筛选变了却拿旧游标翻页，必须显式重来。

    指纹只做一致性校验，不是签名；游标本身仍可被构造，签名/过期见 ADR-0052 待定。
    """
    if not filters.active:
        return None
    payload = {
        "t": filters.tool_name,
        "b": filters.resolved_by,
        "f": filters.resolved_from.isoformat() if filters.resolved_from else None,
        "u": filters.resolved_to.isoformat() if filters.resolved_to else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _encode_approval_cursor(record: ApprovalRecord, filter_fingerprint: str | None = None) -> str:
    """按记录的最终状态编码游标：待办 e/c/i，已办 s/r/i（+ 筛选指纹 f）。"""
    if record.status == "pending":
        payload: dict[str, object] = {
            "e": record.expires_at.isoformat(),
            "c": record.created_at.isoformat(),
            "i": record.id,
        }
    else:
        if record.resolved_at is None:
            # 存储查询已过滤 resolved_at 为空的行；走到这里说明数据不变量被破坏。
            raise RuntimeError("decided approval is missing resolved_at")
        # 已办三种状态共用排序键，必须把 status 写进游标，避免 approved 的
        # 游标被静默用到 rejected 上（ADR-0053）。
        payload = {"s": record.status, "r": record.resolved_at.isoformat(), "i": record.id}
        if filter_fingerprint is not None:
            payload["f"] = filter_fingerprint
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_payload(cursor: str) -> dict[str, object]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise _cursor_error() from exc
    if not isinstance(data, dict):
        raise _cursor_error()
    return data


def _cursor_id(data: dict[str, object]) -> str:
    approval_id = data.get("i")
    if not isinstance(approval_id, str) or not 1 <= len(approval_id) <= 64:
        raise _cursor_error()
    return approval_id


def _cursor_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise _cursor_error()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _cursor_error() from exc
    if parsed.tzinfo is None:
        raise _cursor_error()
    return parsed


def _decode_pending_cursor(data: dict[str, object]) -> PendingApprovalCursor:
    if "e" not in data or "c" not in data:
        raise _cursor_error()
    return PendingApprovalCursor(
        expires_at=_cursor_time(data["e"]),
        created_at=_cursor_time(data["c"]),
        approval_id=_cursor_id(data),
    )


def _decode_resolved_cursor(
    data: dict[str, object], status: str, filter_fingerprint: str | None
) -> ResolvedApprovalCursor:
    if data.get("s") != status or "r" not in data:
        raise _cursor_error()
    if data.get("f") != filter_fingerprint:
        raise _cursor_error()
    return ResolvedApprovalCursor(
        resolved_at=_cursor_time(data["r"]),
        approval_id=_cursor_id(data),
    )


def _decode_approval_cursor(
    cursor: str, status: str, filter_fingerprint: str | None
) -> ApprovalListCursor:
    data = _cursor_payload(cursor)
    if status == "pending":
        return _decode_pending_cursor(data)
    return _decode_resolved_cursor(data, status, filter_fingerprint)


@router.get("/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    identity: Annotated[Identity, Depends(get_identity)],
    status: Annotated[str, Query(pattern="^(pending|approved|rejected|expired)$")] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    tool: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    resolved_by: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resolved_from: Annotated[date | None, Query()] = None,
    resolved_to: Annotated[date | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ApprovalListResponse:
    filters = _approval_filters(
        status,
        tool=tool,
        resolved_by=resolved_by,
        resolved_from=resolved_from,
        resolved_to=resolved_to,
    )
    fingerprint = _filter_fingerprint(filters)
    before = _decode_approval_cursor(cursor, status, fingerprint) if cursor else None
    try:
        records = await service.list_for(
            identity, status=status, limit=limit, filters=filters, cursor=before
        )
    except SQLAlchemyError as exc:
        log.error("approval_list_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return ApprovalListResponse(
        items=[ApprovalOut(**approval_payload(r)) for r in records],
        next_cursor=(
            _encode_approval_cursor(records[-1], fingerprint) if len(records) == limit else None
        ),
    )


@router.get("/approvals/stats", response_model=ApprovalStatsResponse)
async def approval_stats(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    identity: Annotated[Identity, Depends(get_identity)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    group_by: Annotated[ApprovalGroupBy | None, Query()] = None,
) -> ApprovalStatsResponse:
    """审批积压/等待统计（ADR-0048/0050/0051），仅审批人可见。"""
    try:
        stats = await service.stats(identity, days=days, group_by=group_by)
    except ApprovalForbidden as exc:
        raise ApiError(403, "FORBIDDEN", str(exc)) from None
    except SQLAlchemyError as exc:
        log.error("approval_stats_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return ApprovalStatsResponse(
        days=days,
        pending_count=stats.pending_count,
        oldest_pending_age_s=stats.oldest_pending_age_s,
        decided_count=stats.decided_count,
        avg_wait_ms=stats.avg_wait_ms,
        max_wait_ms=stats.max_wait_ms,
        daily=[
            ApprovalDayStatsOut(
                day=day.day, decided_count=day.decided_count, avg_wait_ms=day.avg_wait_ms
            )
            for day in stats.daily
        ],
        groups=[
            ApprovalGroupStatsOut(
                key=group.key,
                decided_count=group.decided_count,
                avg_wait_ms=group.avg_wait_ms,
                max_wait_ms=group.max_wait_ms,
            )
            for group in stats.groups
        ],
        groups_truncated=stats.groups_truncated,
    )


@router.post("/approvals/{approval_id}/resolve", response_model=ApprovalResolveResponse)
async def resolve_approval(
    approval_id: str,
    body: ApprovalResolveRequest,
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    identity: Annotated[Identity, Depends(get_identity)],
    store: Annotated[RunStore, Depends(get_store)],
) -> ApprovalResolveResponse:
    try:
        record = await service.resolve(
            approval_id,
            identity,
            decision=body.decision,
            reason=body.reason,
            scope=body.scope,
        )
    except ApprovalNotFound:
        raise ApiError(404, "APPROVAL_NOT_FOUND", "审批不存在") from None
    except ApprovalForbidden as exc:
        raise ApiError(403, "FORBIDDEN", str(exc)) from None
    except ApprovalNotReady as exc:
        raise ApiError(409, "APPROVAL_NOT_READY", str(exc)) from None
    except ApprovalScopeUnsupported as exc:
        raise ApiError(400, "INVALID_ARGS", str(exc)) from None
    except SQLAlchemyError as exc:
        log.error("approval_resolve_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc

    return ApprovalResolveResponse(
        approval=ApprovalOut(**approval_payload(record)),
        run_id=record.run_id,
        run_status=await store.status(record.run_id),
    )
