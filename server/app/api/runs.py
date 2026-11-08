"""运行查询与断线续传。

事件补拉是"可回放"的基础：客户端记住 lastEventId，重连后按 `after_seq`
（或 SSE 标准头 `Last-Event-ID`）补齐，再决定是否挂增量流。
见 docs/03-api-contract.md 第 3 节。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.core.store import RunRecord, RunStore, get_store

router = APIRouter(tags=["runs"])


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
        "event_count": rec.event_count,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
    }


@router.get("/runs")
async def list_runs() -> dict[str, Any]:
    # TODO(W4 D19): 列表分页 + 筛选；D4 只保证单 run 可查、可回放
    return {"items": [], "next_cursor": None}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    store: Annotated[RunStore, Depends(get_store)],
) -> dict[str, Any]:
    rec = await store.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {**_run_summary(rec), "input": rec.input, "output": rec.output}


@router.get("/runs/{run_id}/events")
async def get_events(
    run_id: str,
    store: Annotated[RunStore, Depends(get_store)],
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> dict[str, Any]:
    # 只取状态：不要再走 get() 的 COUNT(*)，补拉会每秒轮询
    run_status = await store.status(run_id)
    if run_status is None:
        raise HTTPException(status_code=404, detail="run not found")

    # 查询参数优先：显式传 0 表示"从头补"，不会被旧 header 覆盖
    effective_after = after_seq if after_seq is not None else _parse_last_event_id(last_event_id)
    events = await store.events_after(run_id, after_seq=effective_after, limit=limit)
    next_seq = events[-1].seq if events else effective_after
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "next_seq": next_seq,
        "run_status": run_status,
    }
