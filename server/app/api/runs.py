"""运行查询与断线续传。

事件补拉是"可回放"的基础：客户端记住 lastEventId，重连后按 `after_seq`
（或 SSE 标准头 `Last-Event-ID`）补齐，再决定是否挂增量流。
见 docs/03-api-contract.md 第 3 节。

归属校验：只能读自己的 run。别人的 run 统一 404 —— 用 403 会泄露 run 是否存在。
W4 D19 增加列表分页与计量明细；W4 D20 的回放直接复用事件接口。
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_identity
from app.api.errors import ApiError
from app.core.store import RunRecord, RunStore, get_store
from app.gateway.meter import ModelCallStore, get_model_call_store
from app.schemas.cost import ModelCallOut
from app.schemas.event import RunStatus
from app.tools.registry import Identity

router = APIRouter(tags=["runs"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="run not found")


def _parse_last_event_id(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _run_summary(rec: RunRecord) -> dict[str, Any]:
    return {
        "run_id": rec.run_id,
        "status": rec.status,
        "user_id": rec.user_id,
        "session_id": rec.session_id,
        "intent": rec.intent,
        "model": rec.model,
        "step_count": rec.step_count,
        "max_steps": rec.max_steps,
        "token_in": rec.token_in,
        "token_out": rec.token_out,
        "cost_cents": rec.cost_cents,
        "error_code": rec.error_code,
        "failure_category": rec.failure_category,
        "event_count": rec.event_count,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
    }


def _encode_cursor(record: RunRecord) -> str:
    raw = f"{record.started_at.isoformat()}|{record.run_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        started_at, run_id = raw.split("|", 1)
        return datetime.fromisoformat(started_at), run_id
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取") from exc


@router.get("/runs")
async def list_runs(
    store: Annotated[RunStore, Depends(get_store)],
    identity: Annotated[Identity, Depends(get_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    status: Annotated[RunStatus | None, Query()] = None,
) -> dict[str, Any]:
    before_started_at: datetime | None = None
    before_run_id: str | None = None
    if cursor:
        before_started_at, before_run_id = _decode_cursor(cursor)
    try:
        records = await store.list_runs(
            user_id=identity.user_id,
            limit=limit,
            before_started_at=before_started_at,
            before_run_id=before_run_id,
            status=status.value if status else None,
        )
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc

    next_cursor = _encode_cursor(records[-1]) if len(records) == limit else None
    return {"items": [_run_summary(rec) for rec in records], "next_cursor": next_cursor}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    store: Annotated[RunStore, Depends(get_store)],
    calls: Annotated[ModelCallStore, Depends(get_model_call_store)],
    identity: Annotated[Identity, Depends(get_identity)],
) -> dict[str, Any]:
    rec = await store.get(run_id)
    if rec is None or rec.user_id != identity.user_id:
        raise _not_found()
    try:
        records = await calls.list_for_run(run_id)
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return {
        **_run_summary(rec),
        "input": rec.input,
        "output": rec.output,
        "model_calls": [
            ModelCallOut(
                step=item.step,
                provider=item.provider,
                model=item.model,
                token_in=item.token_in,
                token_out=item.token_out,
                cost_cents=item.cost_cents,
                latency_ms=item.latency_ms,
                first_token_ms=item.first_token_ms,
                status=item.status,
                error=item.error,
                created_at=item.created_at,
            ).model_dump(mode="json")
            for item in records
        ],
    }


@router.get("/runs/{run_id}/events")
async def get_events(
    run_id: str,
    store: Annotated[RunStore, Depends(get_store)],
    identity: Annotated[Identity, Depends(get_identity)],
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> dict[str, Any]:
    # 归属用 owner()，状态用 status()：都不要跑 COUNT(*)，补拉会每秒轮询
    owner = await store.owner(run_id)
    if owner is None or owner != identity.user_id:
        raise _not_found()

    run_status = await store.status(run_id)
    if run_status is None:
        raise _not_found()

    # 查询参数优先：显式传 0 表示"从头补"，不会被旧 header 覆盖
    effective_after = after_seq if after_seq is not None else _parse_last_event_id(last_event_id)
    events = await store.events_after(run_id, after_seq=effective_after, limit=limit)
    next_seq = events[-1].seq if events else effective_after
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "next_seq": next_seq,
        "run_status": run_status,
    }
