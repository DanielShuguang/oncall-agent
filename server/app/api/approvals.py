"""审批接口（W3 D14）。

契约见 docs/03 §4：
- 只有审批人角色能决议，且不能审批自己发起的操作
- 幂等：重复 resolve 返回首次结果，不重复执行写工具
- 过期：超过 expires_at 置 expired，run 转 failed(APPROVAL_TIMEOUT)
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_approval_service, get_identity
from app.api.errors import ApiError
from app.approvals.service import ApprovalService, approval_payload
from app.approvals.types import (
    ApprovalForbidden,
    ApprovalGroupBy,
    ApprovalNotFound,
    ApprovalNotReady,
    ApprovalRecord,
    ApprovalScopeUnsupported,
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


def _encode_approval_cursor(record: ApprovalRecord) -> str:
    payload = {
        "e": record.expires_at.isoformat(),
        "c": record.created_at.isoformat(),
        "i": record.id,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_approval_cursor(cursor: str) -> tuple[datetime, datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        if not isinstance(data, dict):
            raise ValueError("cursor payload 不是对象")
        expires_at = datetime.fromisoformat(str(data["e"]))
        created_at = datetime.fromisoformat(str(data["c"]))
        approval_id = str(data["i"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取") from exc
    if expires_at.tzinfo is None or created_at.tzinfo is None or not 1 <= len(approval_id) <= 64:
        raise ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取")
    return expires_at, created_at, approval_id


@router.get("/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    identity: Annotated[Identity, Depends(get_identity)],
    status: Annotated[str, Query(pattern="^(pending|approved|rejected|expired)$")] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ApprovalListResponse:
    before = _decode_approval_cursor(cursor) if cursor else None
    try:
        records = await service.list_for(identity, status=status, limit=limit, before=before)
    except SQLAlchemyError as exc:
        log.error("approval_list_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return ApprovalListResponse(
        items=[ApprovalOut(**approval_payload(r)) for r in records],
        next_cursor=_encode_approval_cursor(records[-1]) if len(records) == limit else None,
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
