"""对话流接口。

事件由 `agent.runtime.stream()` 产出（W1 D5 起是真实运行时：
规则节点 + 工具治理 + 事件流），本层只负责落库、推送与收尾。

关键语义（见 docs/03-api-contract.md）：
- 能建流就返回 200，运行期失败用 run.failed 事件表达
- 每条事件先落库、再推送，保证可回放（R2）
- 客户端断开即停止，并标记 interrupted，不产生"幽灵事件"
- `client_msg_id` 命中时只回放已落库事件，不重复执行；仍在 running 时持续跟到终态
- 空闲每 15s 发 `: heartbeat`，避免代理空闲超时
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.agent.runtime import build_deps
from app.agent.runtime import stream as agent_stream
from app.api.deps import get_approval_service, get_identity
from app.approvals.service import ApprovalService
from app.core.logging import get_logger
from app.core.sse import encode_comment, encode_frame
from app.core.store import RunStore, get_store
from app.schemas.chat import ChatRequest
from app.schemas.event import RunStatus
from app.tools.registry import Identity

router = APIRouter(tags=["chat"])
log = get_logger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # Nginx 不缓冲，否则看不到流式
}

HEARTBEAT_INTERVAL_S = 15.0
REPLAY_POLL_INTERVAL_S = 1.0
REPLAY_TAIL_MAX_S = 300.0


def _resume_after(request: Request) -> int:
    """SSE 重连时浏览器会带 Last-Event-ID；非法值按 0 处理，不让续传拖垮主流程。"""
    raw = request.headers.get("Last-Event-ID")
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


async def _with_heartbeat(
    source: AsyncGenerator[str, None],
    interval: float = HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """在事件之间空闲超过 interval 时补 `: heartbeat` 注释帧。

    用一个 pending task 拉下一帧，`asyncio.wait` 超时就发心跳；客户端断开时
    取消 pending，让内层生成器走 CancelledError 收尾。
    """
    iterator = source
    pending: asyncio.Task[str] = asyncio.ensure_future(iterator.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield encode_comment("heartbeat")
                continue
            try:
                frame = pending.result()
            except StopAsyncIteration:
                return
            yield frame
            pending = asyncio.ensure_future(iterator.__anext__())
    finally:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
        with suppress(RuntimeError):
            await iterator.aclose()


async def _replay(store: RunStore, run_id: str, after_seq: int) -> AsyncGenerator[str, None]:
    """幂等命中：回放已落库事件；仍在 running 就跟到终态。"""
    after = after_seq
    deadline = time.monotonic() + REPLAY_TAIL_MAX_S
    while True:
        status = await store.status(run_id)
        if status is None:
            return

        for event in await store.events_after(run_id, after_seq=after):
            after = event.seq
            yield encode_frame(
                seq=event.seq,
                event=event.type.value,
                data=event.model_dump(mode="json"),
            )

        if status != RunStatus.RUNNING.value or time.monotonic() >= deadline:
            log.info("run_replay_finished", run_id=run_id, after_seq=after, status=status)
            return
        await asyncio.sleep(REPLAY_POLL_INTERVAL_S)


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    store: Annotated[RunStore, Depends(get_store)],
    identity: Annotated[Identity, Depends(get_identity)],
    approval_service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> StreamingResponse:
    run_id = str(uuid.uuid4())
    # W1 没有模型调用（规则节点），W4 网关接入后这里改成按 provider 选模型
    model = req.options.model or "rule-engine"

    try:
        rec, created = await store.create(
            run_id=run_id,
            user_id=identity.user_id,
            session_id=req.session_id,
            message=req.message,
            client_msg_id=req.client_msg_id,
            model=model,
            max_steps=req.options.max_steps,
        )
    except SQLAlchemyError as exc:
        # 建流之前失败 → 503；不要假装 200 再静默截断
        log.error("run_create_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    resumed_after = _resume_after(request)

    async def gen() -> AsyncIterator[str]:
        async for etype, payload in agent_stream(
            run_id=rec.run_id,
            identity=identity,
            query=req.message,
            model=model,
            max_steps=req.options.max_steps,
            session_id=req.session_id,
            deps=build_deps(approvals=approval_service),
        ):
            if await request.is_disconnected():
                log.info("client_disconnected", run_id=rec.run_id)
                await _mark_interrupted(store, rec.run_id)
                return

            try:
                event = await store.append(rec.run_id, etype, payload)
            except SQLAlchemyError as exc:
                # 已经 200 了，不能改成 HTTP 错误；尽力标记失败，客户端靠补拉/重试
                log.error("event_append_failed", run_id=rec.run_id, error=str(exc))
                await _mark_failed(store, rec.run_id, "STORE_WRITE_FAILED")
                return

            yield encode_frame(
                seq=event.seq,
                event=etype.value,
                data=event.model_dump(mode="json"),
            )

        log.info("run_finished", run_id=rec.run_id)

    async def guarded() -> AsyncGenerator[str, None]:
        # 客户端硬断时 Starlette 会直接取消任务，不会走 is_disconnected 分支；
        # shield 保证"标记 interrupted"这个收尾写入不被取消掉。
        try:
            async for frame in gen():
                yield frame
        except asyncio.CancelledError:
            await asyncio.shield(_mark_interrupted(store, rec.run_id))
            raise
        except Exception:
            # 运行期未预期异常：先尽力写失败态，再让连接结束；不能留下永久 running
            log.exception("run_stream_failed", run_id=rec.run_id)
            await asyncio.shield(_mark_failed(store, rec.run_id, "INTERNAL_ERROR"))
            raise

    source = _replay(store, rec.run_id, resumed_after) if not created else guarded()
    return StreamingResponse(
        _with_heartbeat(source),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


async def _mark_interrupted(store: RunStore, run_id: str) -> None:
    try:
        await store.set_status(run_id, RunStatus.INTERRUPTED.value)
    except (SQLAlchemyError, LookupError) as exc:
        log.warning("run_interrupt_mark_failed", run_id=run_id, error=str(exc))


async def _mark_failed(store: RunStore, run_id: str, error_code: str) -> None:
    try:
        await store.set_status(run_id, RunStatus.FAILED.value, error_code=error_code)
    except (SQLAlchemyError, LookupError) as exc:
        log.warning("run_fail_mark_failed", run_id=run_id, error=str(exc))
