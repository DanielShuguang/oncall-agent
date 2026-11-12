"""运行查询与断线续传。

事件补拉是"可回放"的基础：客户端记住 lastEventId，重连后按 `after_seq`
（或 SSE 标准头 `Last-Event-ID`）补齐，再决定是否挂增量流。
见 docs/03-api-contract.md 第 3 节。

归属校验：只能读自己的 run。别人的 run 统一 404 —— 用 403 会泄露 run 是否存在。
W4 D19 增加列表分页与计量明细；W4 D20 的回放直接复用事件接口。
ADR-0022 在读取侧加一层按**当前**可见性的回收：详情不带 `output`、事件不回放、
`content_redacted` 说明原因（列表没有正文，不需要）。
ADR-0023 是**按时间**的正文清理（`content_pruned_at`）：到期后 `input/output` 不再返回，
摘要、计量与失败归因照旧；两种原因同时存在时先说过期（正文已经不存在了）。
ADR-0030 的会话列表也是 runs 的投影：`GET /sessions` 按 `session_id` 聚合，不建表。
ADR-0035 在详情里投影只读运行过程（工具调用/审批），事件仍是唯一真相。
"""

from __future__ import annotations

import base64
import binascii
import json
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
from app.runs.timeline import build_timeline
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
        # 事件过了保留期会被整场清理（ADR-0021）；有值表示回放不可用，摘要仍可信
        "events_pruned_at": rec.events_pruned_at,
        # 正文过了保留期会被清空（ADR-0023）；有值表示 input/output 已不可读
        "content_pruned_at": rec.content_pruned_at,
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
    # 合法游标只有几十个字符；限长避免把解码/JSON 解析暴露给任意大输入
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    status: Annotated[RunStatus | None, Query()] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
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
            session_id=session_id,
        )
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc

    next_cursor = _encode_cursor(records[-1]) if len(records) == limit else None
    return {"items": [_run_summary(rec) for rec in records], "next_cursor": next_cursor}


def _session_title(raw: str | None) -> str | None:
    """会话标题取最早一条输入，空白折叠成单行，最多 60 字符（含省略号）。

    正文被保留策略清空后 `input` 为空串（ADR-0023），会话仍然存在——标题返回
    None，由前端显示「无标题」，不能因此把会话藏掉。
    """
    if not raw:
        return None
    text = " ".join(raw.split())
    if not text:
        return None
    if len(text) <= 60:
        return text
    return text[:59] + "…"


def _encode_session_cursor(updated_at: datetime, session_id: str) -> str:
    """会话列表的 keyset 游标：`(updated_at, session_id)`，base64(JSON) 对前端不透明。

    不用 `isoformat|session_id` 拼接，因为 session_id 由客户端生成（1–64 字符），
    可能包含分隔符。
    """
    raw = json.dumps({"t": updated_at.isoformat(), "s": session_id}, ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_session_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("cursor must be an object")
        updated_at = datetime.fromisoformat(str(data["t"]))
        session_id = data["s"]
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 64:
            raise ValueError("invalid session id")
        if updated_at.tzinfo is None:
            raise ValueError("cursor datetime must be timezone-aware")
        return updated_at.astimezone(UTC), session_id
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiError(400, "INVALID_CURSOR", "cursor 无效，请从第一页重新拉取") from exc


@router.get("/sessions")
async def list_sessions(
    store: Annotated[RunStore, Depends(get_store)],
    identity: Annotated[Identity, Depends(get_identity)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> dict[str, Any]:
    """当前用户最近的会话（ADR-0030），按最近活动 keyset 分页（ADR-0033）。

    会话是 `runs.session_id` 的投影，没有独立表。`next_cursor` 只在当前页取满时
    返回；新 run 会把会话移到列表前面，翻页途中可能重复或跳过一页，刷新即重置。
    """
    before_updated_at: datetime | None = None
    before_session_id: str | None = None
    if cursor:
        before_updated_at, before_session_id = _decode_session_cursor(cursor)
    try:
        sessions = await store.list_sessions(
            user_id=identity.user_id,
            limit=limit,
            before_updated_at=before_updated_at,
            before_session_id=before_session_id,
        )
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    next_cursor = (
        _encode_session_cursor(sessions[-1].updated_at, sessions[-1].session_id)
        if len(sessions) == limit
        else None
    )
    return {
        "items": [
            {
                "session_id": item.session_id,
                "title": _session_title(item.title),
                "run_count": item.run_count,
                "started_at": item.started_at,
                "updated_at": item.updated_at,
            }
            for item in sessions
        ],
        "next_cursor": next_cursor,
    }


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
        # 运行过程跟随回答的可见性：正文被回收/过期后，工具参数与审批理由也不
        # 再展示（它们同样属于那一轮的内容）。没有回答正文（失败/未完成）时也
        # 不返回过程；事件已清理时明确告诉前端「不可用」，不把它伪装成
        # 「这轮没调工具」。
        timeline_available = (
            rec.output is not None
            and not redacted
            and rec.events_pruned_at is None
            and rec.content_pruned_at is None
        )
        timeline: list[dict[str, Any]] = []
        timeline_truncated = False
        if timeline_available:
            timeline, timeline_truncated = build_timeline(
                await store.events_after(run_id, limit=500)
            )
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return {
        **_run_summary(rec),
        # 正文被保留策略清空后 input 是空串、output 是 null（ADR-0023）；
        # 用 content_pruned_at 区分「本来就空」和「过期清理」
        "input": rec.input,
        "output": None if redacted else rec.output,
        "content_redacted": redacted,
        # 引用快照供历史会话还原角标（ADR-0031）。正文没生成、被权限回收或按时间
        # 清空时都不返回：没有可指的答案，片段也不能比 output 活得更久。
        "citations": (
            []
            if redacted or rec.content_pruned_at is not None or rec.output is None
            else rec.citations
        ),
        # 只读运行过程（ADR-0035）：工具调用/审批的短列表，事件已清理或内容被
        # 回收时为空，并用 timeline_available 区分「没有过程」与「过程不可用」。
        "timeline": timeline,
        "timeline_available": timeline_available,
        "timeline_truncated": timeline_truncated,
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

    # 查询参数优先：显式传 0 表示"从头补"，不会被旧 header 覆盖
    effective_after = after_seq if after_seq is not None else _parse_last_event_id(last_event_id)

    # 回答引用的文档已不可见时，事件里的 message.completed（带切片原文）也不能再回放
    # （ADR-0022）。和保留清理一样返回 200 + 空数组：run 本身存在、状态仍可读，
    # 具体原因看 /runs/{id} 的 content_redacted / events_pruned_at / content_pruned_at。
    # 这里不按状态放行：只多一次主键查询（没有引用就不会查知识库），换的是
    # 「详情与事件同一条规则」——运行中但已有引用快照的 run（回答输出到一半崩掉）
    # 也不能靠读接口绕过去。
    #
    # 正文过了保留期（ADR-0023）时事件早已按 ADR-0021 清掉，也没有「权限回收」可言：
    # 直接返回同样形态的空数组，和详情的 `content_redacted: false` 保持一致口径
    # （一次查询同时取引用快照与过期标记，不额外加一次往返）。
    state = await store.content_state(run_id)
    if state is None:
        raise _not_found()
    if state.content_pruned_at is not None:
        return {
            "events": [],
            "next_seq": effective_after,
            "run_status": run_status,
            "content_redacted": False,
        }
    try:
        redacted = not await content_is_visible(
            cited_document_ids=state.cited_document_ids, viewer=viewer, kb=kb
        )
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc

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
