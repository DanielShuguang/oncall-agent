"""对话流接口。

当前返回 `agent.demo` 的脚本化事件（W1 D3 骨架）；W1 D5 之后
换成 `agent.runtime.stream()`，接口与事件格式不变。

关键语义（见 docs/03-api-contract.md）：
- 能建流就返回 200，运行期失败用 run.failed 事件表达
- 每条事件先落库、再推送，保证可回放（R2）
- 客户端断开即停止，并标记 interrupted，不产生"幽灵事件"
- `client_msg_id` 命中时只回放已落库事件，不重复执行
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.agent.demo import demo_stream
from app.core.logging import get_logger
from app.core.sse import encode_frame
from app.core.store import RunStore, get_store
from app.schemas.chat import ChatRequest
from app.schemas.event import RunStatus

router = APIRouter(tags=["chat"])
log = get_logger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # Nginx 不缓冲，否则看不到流式
}


def _resume_after(request: Request) -> int:
    """SSE 重连时浏览器会带 Last-Event-ID；非法值按 0 处理，不让续传拖垮主流程。"""
    raw = request.headers.get("Last-Event-ID")
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    store: Annotated[RunStore, Depends(get_store)],
) -> StreamingResponse:
    run_id = str(uuid.uuid4())

    # TODO(W1 D2): 从 JWT 取真实身份；当前为单用户演示
    try:
        rec, created = await store.create(
            run_id=run_id,
            user_id="u_102",
            session_id=req.session_id,
            message=req.message,
            client_msg_id=req.client_msg_id,
            model=req.options.model,
            max_steps=req.options.max_steps,
        )
    except SQLAlchemyError as exc:
        # 建流之前失败 → 503；不要假装 200 再静默截断
        log.error("run_create_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    resumed_after = _resume_after(request)

    async def gen() -> AsyncIterator[str]:
        if not created:
            # 幂等：重复提交只回放事件，不重跑 Agent
            for event in await store.events_after(rec.run_id, after_seq=resumed_after):
                yield encode_frame(
                    seq=event.seq,
                    event=event.type.value,
                    data=event.model_dump(mode="json"),
                )
            log.info("run_replayed", run_id=rec.run_id, after_seq=resumed_after)
            return

        async for etype, payload in demo_stream(req.message):
            if await request.is_disconnected():
                log.info("client_disconnected", run_id=rec.run_id)
                await _mark_interrupted(store, rec.run_id)
                return

            try:
                event = await store.append(rec.run_id, etype, payload)
            except SQLAlchemyError as exc:
                # 已经 200 了，不能改成 HTTP 错误；记日志并截断，客户端靠补拉恢复
                log.error("event_append_failed", run_id=rec.run_id, error=str(exc))
                return

            yield encode_frame(
                seq=event.seq,
                event=etype.value,
                data=event.model_dump(mode="json"),
            )

        log.info("run_finished", run_id=rec.run_id)

    return StreamingResponse(gen(), media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS)


async def _mark_interrupted(store: RunStore, run_id: str) -> None:
    try:
        await store.set_status(run_id, RunStatus.INTERRUPTED.value)
    except (SQLAlchemyError, LookupError) as exc:
        log.warning("run_interrupt_mark_failed", run_id=run_id, error=str(exc))
