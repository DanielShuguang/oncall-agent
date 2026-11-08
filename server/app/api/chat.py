"""对话流接口。

当前返回 `agent.demo` 的脚本化事件（W1 D3 骨架）；W1 D5 之后
换成 `agent.runtime.stream()`，接口与事件格式不变。

关键语义（见 docs/03-api-contract.md）：
- 能建流就返回 200，运行期失败用 run.failed 事件表达
- 每条事件先落库、再推送，保证可回放
- 客户端断开即停止，不产生"幽灵事件"
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agent.demo import demo_stream
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.sse import encode_frame
from app.core.store import store
from app.schemas.chat import ChatRequest
from app.schemas.event import EventType, RunEvent, RunStatus

router = APIRouter(tags=["chat"])
log = get_logger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # Nginx 不缓冲，否则看不到流式
}


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    settings = get_settings()
    run_id = uuid.uuid4().hex

    # TODO(W1 D2): 从 JWT 取真实身份；当前为单用户演示
    rec = await store.create(
        run_id=run_id,
        user_id="u_102",
        session_id=req.session_id,
        client_msg_id=req.client_msg_id,
    )

    async def gen() -> AsyncIterator[str]:
        async for etype, payload in demo_stream(req.message):
            if await request.is_disconnected():
                log.info("client_disconnected", run_id=rec.run_id)
                rec.status = RunStatus.INTERRUPTED.value
                return

            seq = rec.next_seq()
            event = RunEvent(seq=seq, run_id=rec.run_id, type=etype, payload=payload)
            await store.append(rec.run_id, event)

            if etype is EventType.RUN_COMPLETED:
                rec.status = RunStatus.COMPLETED.value
            elif etype is EventType.APPROVAL_REQUIRED:
                rec.status = RunStatus.AWAITING_APPROVAL.value
            elif etype is EventType.RUN_FAILED:
                rec.status = RunStatus.FAILED.value

            yield encode_frame(
                seq=seq,
                event=etype.value,
                data=event.model_dump(mode="json"),
            )

        log.info("run_finished", run_id=rec.run_id, status=rec.status)

    return StreamingResponse(gen(), media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS)
