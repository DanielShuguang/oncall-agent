"""审批接口（W3 D14）。

契约见 docs/03 §4：
- 只有审批人角色能决议，且不能审批自己发起的操作
- 幂等：重复 resolve 返回首次结果，不重复执行写工具
- 过期：超过 expires_at 置 expired，run 转 failed(APPROVAL_TIMEOUT)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_approval_service, get_identity
from app.api.errors import ApiError
from app.approvals.service import ApprovalService, approval_payload
from app.approvals.types import (
    ApprovalForbidden,
    ApprovalNotFound,
    ApprovalNotReady,
    ApprovalScopeUnsupported,
)
from app.core.logging import get_logger
from app.core.store import RunStore, get_store
from app.schemas.approval import (
    ApprovalListResponse,
    ApprovalOut,
    ApprovalResolveRequest,
    ApprovalResolveResponse,
)
from app.tools.registry import Identity

router = APIRouter(tags=["approvals"])
log = get_logger(__name__)


@router.get("/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    identity: Annotated[Identity, Depends(get_identity)],
    status: Annotated[str, Query(pattern="^(pending|approved|rejected|expired)$")] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApprovalListResponse:
    try:
        records = await service.list_for(identity, status=status, limit=limit)
    except SQLAlchemyError as exc:
        log.error("approval_list_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return ApprovalListResponse(items=[ApprovalOut(**approval_payload(r)) for r in records])


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
