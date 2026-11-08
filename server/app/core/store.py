"""运行态存储。

默认实现是 PostgreSQL：事件先落库、再推送（R2），`runs` 的汇总字段由事件
投影得到（docs/02 §3）。内存实现只用于测试与显式 `ONCALL_STORE_BACKEND=memory`，
**不做静默降级** —— 库挂了要让人看见，不能悄悄写内存然后重启丢数据。

`seq` 用「锁 run 行 + MAX(seq)+1」在同一事务内生成：单 run 的写入是串行的，
比时间戳排序可靠（R7）；并发量级（一个 run 一条流）不值得为每 run 建序列。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.run import Run
from app.models.run import RunEvent as RunEventRow
from app.schemas.event import EventType, RunEvent, RunStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings


class RunNotFoundError(LookupError):
    """run_id 不存在。API 层翻译成 404，不要吞掉。"""


@dataclass
class RunRecord:
    run_id: str
    user_id: str
    session_id: str
    input: str
    status: str = RunStatus.RUNNING.value
    intent: str | None = None
    model: str | None = None
    output: str | None = None
    step_count: int = 0
    max_steps: int = 12
    token_in: int = 0
    token_out: int = 0
    cost_cents: int = 0
    error_code: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    event_count: int = 0


@dataclass(frozen=True)
class RunPatch:
    """事件对 runs 汇总字段的投影。None 表示该字段不更新。"""

    status: str | None = None
    finished_at: datetime | None = None
    output: str | None = None
    error_code: str | None = None
    model: str | None = None
    max_steps: int | None = None
    step_count: int | None = None
    token_in: int | None = None
    token_out: int | None = None
    cost_cents: int | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in self.__dataclass_fields__)


_TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.INTERRUPTED.value,
}


def build_run_patch(
    event_type: EventType, payload: dict[str, Any], at: datetime
) -> RunPatch:
    """把事件翻译成 runs 的字段补丁。

    只做「事件 → 当前态」的机械投影，不判断业务对错；审批超时等语义由
    发事件的 runtime 决定（W3）。
    """
    if event_type is EventType.RUN_STARTED:
        patch = RunPatch(status=RunStatus.RUNNING.value)
        if isinstance(payload.get("model"), str):
            patch = RunPatch(
                status=patch.status, model=payload["model"], max_steps=_int_or_none(payload.get("max_steps"))
            )
        return patch

    if event_type is EventType.APPROVAL_REQUIRED:
        return RunPatch(status=RunStatus.AWAITING_APPROVAL.value)

    if event_type is EventType.APPROVAL_RESOLVED:
        decision = payload.get("status")
        if decision == "approved":
            return RunPatch(status=RunStatus.RUNNING.value)
        if decision == "expired":
            return RunPatch(
                status=RunStatus.FAILED.value,
                finished_at=at,
                error_code="APPROVAL_EXPIRED",
            )
        return RunPatch(
            status=RunStatus.FAILED.value,
            finished_at=at,
            error_code="APPROVAL_REJECTED",
        )

    if event_type is EventType.MESSAGE_COMPLETED:
        text = payload.get("text")
        return RunPatch(output=text) if isinstance(text, str) else RunPatch()

    if event_type is EventType.RUN_COMPLETED:
        return RunPatch(
            status=RunStatus.COMPLETED.value,
            finished_at=at,
            step_count=_int_or_none(payload.get("steps")),
            token_in=_int_or_none(payload.get("token_in")),
            token_out=_int_or_none(payload.get("token_out")),
            cost_cents=_int_or_none(payload.get("cost_cents")),
        )

    if event_type is EventType.RUN_FAILED:
        code = payload.get("error_code")
        return RunPatch(
            status=RunStatus.FAILED.value,
            finished_at=at,
            error_code=code if isinstance(code, str) else "UNKNOWN",
        )

    return RunPatch()


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _apply_patch(record: RunRecord, patch: RunPatch) -> None:
    for name in patch.__dataclass_fields__:
        value = getattr(patch, name)
        if value is not None:
            setattr(record, name, value)


class RunStore(Protocol):
    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str,
        message: str,
        client_msg_id: str | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> tuple[RunRecord, bool]:
        """创建 run；`client_msg_id` 命中时返回已存在的 run 且 created=False。"""
        ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        """追加事件并更新 runs 汇总字段，同一事务内完成。"""
        ...

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]: ...

    async def set_status(
        self, run_id: str, status: str, *, error_code: str | None = None
    ) -> None: ...


class InMemoryRunStore:
    """测试与 demo 用。事件只在进程内，重启即丢。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[str, list[RunEvent]] = {}
        self._client_index: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str,
        message: str,
        client_msg_id: str | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> tuple[RunRecord, bool]:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            if client_msg_id and client_msg_id in self._client_index:
                existing = self._client_index[client_msg_id]
                return self._runs[existing], False
            record = RunRecord(
                run_id=rid,
                user_id=user_id,
                session_id=session_id,
                input=message,
                model=model,
                max_steps=max_steps,
            )
            self._runs[rid] = record
            self._events[rid] = []
            if client_msg_id:
                self._client_index[client_msg_id] = rid
            return record, True

    async def get(self, run_id: str) -> RunRecord | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        if record is not None:
            record.event_count = len(self._events[rid])
        return record

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            record = self._runs.get(rid)
            if record is None:
                raise RunNotFoundError(run_id)
            now = datetime.now(UTC)
            event = RunEvent(
                seq=len(self._events[rid]) + 1,
                run_id=rid,
                type=event_type,
                ts=now,
                payload=payload or {},
            )
            self._events[rid].append(event)
            record.event_count = len(self._events[rid])
            _apply_patch(record, build_run_patch(event_type, event.payload, now))
            return event

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return []
        return [e for e in self._events.get(rid, []) if e.seq > after_seq][:limit]

    async def set_status(
        self, run_id: str, status: str, *, error_code: str | None = None
    ) -> None:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            record = self._runs.get(rid)
            if record is None:
                raise RunNotFoundError(run_id)
            record.status = status
            if error_code is not None:
                record.error_code = error_code
            if status in _TERMINAL_STATUSES:
                record.finished_at = datetime.now(UTC)


class PostgresRunStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str,
        message: str,
        client_msg_id: str | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> tuple[RunRecord, bool]:
        rid = uuid.UUID(run_id)
        if client_msg_id:
            existing = await self._find_by_client_msg_id(client_msg_id)
            if existing is not None:
                return existing, False

        row = Run(
            id=rid,
            client_msg_id=client_msg_id,
            user_id=user_id,
            session_id=session_id,
            status=RunStatus.RUNNING.value,
            input=message,
            model=model,
            max_steps=max_steps,
            started_at=datetime.now(UTC),
        )
        async with self._sessionmaker() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                # 并发重复提交：唯一约束兜底，回读先落库的那条
                await session.rollback()
                if client_msg_id:
                    existing = await self._find_by_client_msg_id(client_msg_id)
                    if existing is not None:
                        return existing, False
                raise
        return _record_from_row(row, event_count=0), True

    async def get(self, run_id: str) -> RunRecord | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            row = await session.get(Run, rid)
            if row is None:
                return None
            count = await session.scalar(
                select(func.count()).select_from(RunEventRow).where(RunEventRow.run_id == rid)
            )
        return _record_from_row(row, event_count=int(count or 0))

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        rid = uuid.UUID(run_id)
        data = payload or {}
        async with self._sessionmaker() as session, session.begin():
            # 行锁保证同一 run 的 seq 分配串行，避免 MAX(seq)+1 并发撞主键
            row = await session.scalar(select(Run).where(Run.id == rid).with_for_update())
            if row is None:
                raise RunNotFoundError(run_id)

            last_seq = await session.scalar(
                select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == rid)
            )
            seq = int(last_seq or 0) + 1
            now = datetime.now(UTC)
            session.add(
                RunEventRow(run_id=rid, seq=seq, type=event_type.value, payload=data, created_at=now)
            )

            patch = build_run_patch(event_type, data, now)
            for name in patch.__dataclass_fields__:
                value = getattr(patch, name)
                if value is not None:
                    setattr(row, name, value)

            await session.flush()

        return RunEvent(seq=seq, run_id=str(rid), type=event_type, ts=now, payload=data)

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return []
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(RunEventRow)
                    .where(RunEventRow.run_id == rid, RunEventRow.seq > after_seq)
                    .order_by(RunEventRow.seq)
                    .limit(limit)
                )
            ).all()
        return [_event_from_row(row) for row in rows]

    async def set_status(
        self, run_id: str, status: str, *, error_code: str | None = None
    ) -> None:
        rid = uuid.UUID(run_id)
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(Run, rid, with_for_update=True)
            if row is None:
                raise RunNotFoundError(run_id)
            row.status = status
            if error_code is not None:
                row.error_code = error_code
            if status in _TERMINAL_STATUSES:
                row.finished_at = datetime.now(UTC)

    async def _find_by_client_msg_id(self, client_msg_id: str) -> RunRecord | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(select(Run).where(Run.client_msg_id == client_msg_id))
            if row is None:
                return None
            count = await session.scalar(
                select(func.count())
                .select_from(RunEventRow)
                .where(RunEventRow.run_id == row.id)
            )
        return _record_from_row(row, event_count=int(count or 0))


def _record_from_row(row: Run, *, event_count: int) -> RunRecord:
    return RunRecord(
        run_id=str(row.id),
        user_id=row.user_id,
        session_id=row.session_id,
        input=row.input,
        status=row.status,
        intent=row.intent,
        model=row.model,
        output=row.output,
        step_count=row.step_count,
        max_steps=row.max_steps,
        token_in=row.token_in,
        token_out=row.token_out,
        cost_cents=row.cost_cents,
        error_code=row.error_code,
        started_at=row.started_at,
        finished_at=row.finished_at,
        event_count=event_count,
    )


def _event_from_row(row: RunEventRow) -> RunEvent:
    return RunEvent(
        seq=row.seq,
        run_id=str(row.run_id),
        type=EventType(row.type),
        ts=row.created_at,
        payload=row.payload or {},
    )


_store: RunStore | None = None


def build_store(settings: Settings) -> RunStore:
    backend = settings.store_backend.strip().lower()
    if backend == "memory":
        return InMemoryRunStore()
    if backend == "postgres":
        from app.core.db import get_sessionmaker

        return PostgresRunStore(get_sessionmaker())
    raise ValueError(f"unknown ONCALL_STORE_BACKEND: {settings.store_backend!r}")


def get_store() -> RunStore:
    """FastAPI 依赖。测试用 `app.dependency_overrides[get_store]` 替换。"""
    global _store
    if _store is None:
        from app.core.config import get_settings

        _store = build_store(get_settings())
    return _store


def set_store(value: RunStore | None) -> None:
    """测试钩子；生产启动时不要调用。"""
    global _store
    _store = value
