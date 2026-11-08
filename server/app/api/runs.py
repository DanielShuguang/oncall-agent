"""运行查询与断线续传。

事件补拉是"可回放"的基础：前端记住 lastEventId，重连后按 after_seq 补齐，
再决定是否挂增量流。见 docs/03-api-contract.md 第 3 节。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.store import store

router = APIRouter(tags=["runs"])


@router.get("/runs")
async def list_runs() -> dict[str, Any]:
    # TODO(W4 D19): 接 Postgres + 分页
    return {"items": [], "next_cursor": None}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    rec = store.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": rec.run_id,
        "status": rec.status,
        "user_id": rec.user_id,
        "session_id": rec.session_id,
        "event_count": len(rec.events),
    }


@router.get("/runs/{run_id}/events")
async def get_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    rec = store.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="run not found")

    events = store.events_after(run_id, after_seq=after_seq, limit=limit)
    next_seq = events[-1].seq if events else after_seq
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "next_seq": next_seq,
        "run_status": rec.status,
    }
