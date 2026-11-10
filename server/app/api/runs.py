"""运行查询与断线续传。

事件补拉是"可回放"的基础：客户端记住 lastEventId，重连后按 `after_seq`
（或 SSE 标准头 `Last-Event-ID`）补齐，再决定是否挂增量流。
见 docs/03-api-contract.md 第 3 节。

归属校验：只能读自己的 run。别人的 run 统一 404 —— 用 403 会泄露 run 是否存在。
W4 D19 增加列表分页与计量明细；W4 D20 的回放直接复用事件接口。
ADR-0022 在读取侧加一层按**当前**可见性的回收：详情不带 `output`、事件不回放、
`content_redacted` 说明原因（列表没有正文，不需要）。
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_identity, get_viewer
from app.api.errors import ApiError
from app.core.store import RunRecord, RunStore, get_store
from app.gateway.meter import ModelCallStore, get_model_call_store
from app.rag.access import Viewer
from app.rag.retrieve import KnowledgeBase
from app.rag.service import get_knowledge_base
from app.runs.content import content_is_redacted, content_is_visible
from app.schemas.cost import ModelCallOut
from app.schemas.event import RunStatus
from app.tools.registry import Identity

router = APIRouter(tags=["runs"])

#: 回答引用快照只会在 message.completed 之后出现；非终态 run 不做可见性校验
_CONTENT_GATED_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.INTERRUPTED.value,
}


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
        # 事件过了保留期会被整场清理（ADR-0021）；有值表示回放不可用，摘要仍可信
        "events_pruned_at": rec.events_pruned_at,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
    }


def _encode_cursor(record: RunRecord) -> str:
    raw = f"{record.started_at.isoformat()}|{record.run_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        started_at_raw, run_id = raw.split("|", 1)
        started_at = datetime.fromisoformat(started_at_raw)
        # 无时区的游标会让 Postgres 在比较 timestamptz 时行为不确定，
        # 非法 UUID 则会让 keyset 分页退化成只按时间比较、可能跳过同一时刻的记录。
        if started_at.tzinfo is None:
            raise ValueError("cursor datetime must be timezone-aware")
        return started_at.astimezone(UTC), str(uuid.UUID(run_id))
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
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    viewer: Annotated[Viewer, Depends(get_viewer)],
) -> dict[str, Any]:
    rec = await store.get(run_id)
    if rec is None or rec.user_id != identity.user_id:
        raise _not_found()
    try:
        records = await calls.list_for_run(run_id)
        # 回答引用的文档要按**当前**角色重新校验（ADR-0022）：撤权后旧回答正文
        # 不能再从详情接口吐出来。没有引用时不会查知识库。
        redacted = await content_is_redacted(rec, viewer=viewer, kb=kb)
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return {
        **_run_summary(rec),
        "input": rec.input,
        "output": None if redacted else rec.output,
        "content_redacted": redacted,
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
    kb: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    viewer: Annotated[Viewer, Depends(get_viewer)],
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

    # 回答引用的文档已不可见时，事件里的 message.completed（带切片原文）也不能再回放
    # （ADR-0022）。和保留清理一样返回 200 + 空数组：run 本身存在、状态仍可读，
    # 具体原因看 /runs/{id} 的 content_redacted / events_pruned_at。
    # 引用快照只会在 message.completed 之后出现，所以非终态 run 不付这次主键查询——
    # 补拉会被客户端每秒轮询，运行中的 run 本来就没有引用可校验。
    cited: list[str] = []
    if run_status in _CONTENT_GATED_STATUSES:
        latest = await store.cited_document_ids(run_id)
        if latest is None:
            raise _not_found()
        cited = latest
    try:
        redacted = not await content_is_visible(cited_document_ids=cited, viewer=viewer, kb=kb)
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc

    # 查询参数优先：显式传 0 表示"从头补"，不会被旧 header 覆盖
    effective_after = after_seq if after_seq is not None else _parse_last_event_id(last_event_id)
    if redacted:
        return {
            "events": [],
            "next_seq": effective_after,
            "run_status": run_status,
            "content_redacted": True,
        }

    # 事件可能已被保留策略整场清理（ADR-0021）：仍返回 200 + 空数组，因为 run
    # 本身存在、状态仍可读；要区分「没有事件」和「清理过」看 /runs/{id} 的
    # events_pruned_at。

    events = await store.events_after(run_id, after_seq=effective_after, limit=limit)
    next_seq = events[-1].seq if events else effective_after
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "next_seq": next_seq,
        "run_status": run_status,
        "content_redacted": False,
    }
