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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.models.run import Run
from app.models.run import RunEvent as RunEventRow
from app.schemas.event import EventType, RunEvent, RunStatus
from app.schemas.failure import FailureCategory, categorize

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings

log = get_logger(__name__)


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
    failure_category: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    event_count: int = 0


@dataclass(frozen=True)
class StaleRun:
    """超过阈值没有任何事件的 running run（ADR-0017）。

    只给运维回收用；正常读写路径不依赖它。`last_event_at` 在没有事件时回退到
    `started_at`，覆盖「建完 run 还没写 run.started 就崩了」的情况。
    """

    run_id: str
    user_id: str
    started_at: datetime
    last_event_at: datetime


@dataclass(frozen=True)
class RunTurn:
    """已结束的一轮问答（ADR-0020 多轮上下文用）。

    只取用户输入与最终回答这两段投影，不读事件流：多轮上下文是「上一轮说了什么」，
    不是「上一轮调了哪些工具」。工具结果、审批载荷不进上下文，避免跨轮的旧证据混进答案。
    """

    query: str
    answer: str


@dataclass(frozen=True)
class RunPatch:
    """事件对 runs 汇总字段的投影。None 表示该字段不更新。"""

    status: str | None = None
    finished_at: datetime | None = None
    output: str | None = None
    error_code: str | None = None
    failure_category: str | None = None
    model: str | None = None
    max_steps: int | None = None
    step_count: int | None = None
    token_in: int | None = None
    token_out: int | None = None
    cost_cents: int | None = None


_TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.INTERRUPTED.value,
}


def build_run_patch(event_type: EventType, payload: dict[str, Any], at: datetime) -> RunPatch:
    """把事件翻译成 runs 的字段补丁。

    只做「事件 → 当前态」的机械投影，不判断业务对错；审批超时等语义由
    发事件的 runtime 决定（W3）。
    """
    if event_type is EventType.RUN_STARTED:
        model = payload.get("model")
        return RunPatch(
            status=RunStatus.RUNNING.value,
            model=model if isinstance(model, str) else None,
            max_steps=_int_or_none(payload.get("max_steps")),
        )

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
                error_code="APPROVAL_TIMEOUT",
                failure_category=FailureCategory.APPROVAL.value,
            )
        return RunPatch(
            status=RunStatus.FAILED.value,
            finished_at=at,
            error_code="APPROVAL_REJECTED",
            failure_category=FailureCategory.APPROVAL.value,
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
        error_code = code if isinstance(code, str) else "UNKNOWN"
        category = payload.get("category")
        if not isinstance(category, str):
            category = categorize(error_code).value
        else:
            try:
                category = FailureCategory(category).value
            except ValueError:
                category = categorize(error_code).value
        return RunPatch(
            status=RunStatus.FAILED.value,
            finished_at=at,
            error_code=error_code,
            failure_category=category,
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

    async def find_by_client_msg_id(self, user_id: str, client_msg_id: str) -> RunRecord | None:
        """幂等命中查询；限流拒绝前用它判断是否只是重放已有 run。"""
        ...

    async def status(self, run_id: str) -> str | None: ...

    async def owner(self, run_id: str) -> str | None:
        """run 的 user_id；不存在返回 None。路由层做归属校验用，不要为此跑 COUNT。"""
        ...

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

    async def list_stale_runs(self, *, older_than: datetime, limit: int = 100) -> list[StaleRun]:
        """`running` 且最后一条事件（没有事件时用 `started_at`）早于 `older_than`。"""
        ...

    async def fail_stale_run(
        self, run_id: str, *, older_than: datetime, payload: dict[str, Any]
    ) -> bool:
        """原子地把「仍然 running 且确实过期」的 run 追加 `run.failed`。

        返回是否真的写入。状态检查、过期检查与事件写入在同一事务里完成，
        多副本同时回收也只会有一次成功；刚有新事件或已进入终态的 run 不会被误杀。
        """
        ...

    async def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_started_at: datetime | None = None,
        before_run_id: str | None = None,
        status: str | None = None,
    ) -> list[RunRecord]:
        """按 started_at 倒序；`(before_started_at, before_run_id)` 是上一页游标。"""
        ...

    async def recent_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 3,
        exclude_run_id: str | None = None,
    ) -> list[RunTurn]:
        """同一用户同一会话里**已经有回答**的最近 `limit` 轮，按时间正序返回。

        只认 `runs.output` 非空：拒答也是回答（"知识库里没有"本身要进上下文），
        但还没走完的 run（挂起审批 / 正在跑 / 中断）没有 output，不能当成历史，
        否则用户会看到模型"记得"一句它从未说过的话。
        """
        ...


class InMemoryRunStore:
    """测试与 demo 用。事件只在进程内，重启即丢。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[str, list[RunEvent]] = {}
        self._client_index: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()
        self._started_at: datetime | None = None

    def _next_started_at(self) -> datetime:
        """单调递增的创建时间。

        Windows 的 `datetime.now()` 分辨率约 1ms：连续创建的两个 run 会拿到相同时间，
        而排序/分页的次序化依赖 `started_at`（R7 的时间口径）。内存实现里补一个微秒，
        让「先创建的排在前面」成为确定行为，而不是靠 uuid 随机序当第二排序键。
        """
        now = datetime.now(UTC)
        if self._started_at is not None and now <= self._started_at:
            now = self._started_at + timedelta(microseconds=1)
        self._started_at = now
        return now

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
        client_msg_id = client_msg_id or None
        key = (user_id, client_msg_id) if client_msg_id else None
        async with self._lock:
            if key is not None and key in self._client_index:
                existing = self._client_index[key]
                return self._runs[existing], False
            record = RunRecord(
                run_id=rid,
                user_id=user_id,
                session_id=session_id,
                input=message,
                model=model,
                max_steps=max_steps,
                started_at=self._next_started_at(),
            )
            self._runs[rid] = record
            self._events[rid] = []
            if key is not None:
                self._client_index[key] = rid
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

    async def find_by_client_msg_id(self, user_id: str, client_msg_id: str) -> RunRecord | None:
        rid = self._client_index.get((user_id, client_msg_id))
        if rid is None:
            return None
        record = self._runs.get(rid)
        if record is not None:
            record.event_count = len(self._events[rid])
        return record

    async def status(self, run_id: str) -> str | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        return record.status if record is not None else None

    async def owner(self, run_id: str) -> str | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        return record.user_id if record is not None else None

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            return self._append_locked(rid, event_type, payload)

    def _append_locked(
        self, rid: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        record = self._runs.get(rid)
        if record is None:
            raise RunNotFoundError(rid)
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
        if event_type is EventType.STEP_COMPLETED:
            # 失败 run 也需要“跑了几步”的口径；run.completed 会覆盖为准确值
            record.step_count += 1
        return event

    def _last_activity_locked(self, rid: str) -> datetime:
        events = self._events.get(rid) or []
        return events[-1].ts if events else self._runs[rid].started_at

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return []
        return [e for e in self._events.get(rid, []) if e.seq > after_seq][:limit]

    async def set_status(self, run_id: str, status: str, *, error_code: str | None = None) -> None:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            record = self._runs.get(rid)
            if record is None:
                raise RunNotFoundError(run_id)
            # 终态是事件流的结果，不能被断连收尾覆盖（run.completed 后断开很常见）
            if record.status in _TERMINAL_STATUSES:
                return
            record.status = status
            if error_code is not None:
                record.error_code = error_code
                record.failure_category = categorize(error_code).value
            if status in _TERMINAL_STATUSES:
                record.finished_at = datetime.now(UTC)

    async def list_stale_runs(self, *, older_than: datetime, limit: int = 100) -> list[StaleRun]:
        async with self._lock:
            items: list[StaleRun] = []
            for rid, record in self._runs.items():
                if record.status != RunStatus.RUNNING.value:
                    continue
                last = self._last_activity_locked(rid)
                if last >= older_than:
                    continue
                items.append(
                    StaleRun(
                        run_id=rid,
                        user_id=record.user_id,
                        started_at=record.started_at,
                        last_event_at=last,
                    )
                )
        items.sort(key=lambda item: item.started_at)
        return items[:limit]

    async def fail_stale_run(
        self, run_id: str, *, older_than: datetime, payload: dict[str, Any]
    ) -> bool:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return False
        async with self._lock:
            record = self._runs.get(rid)
            if record is None or record.status != RunStatus.RUNNING.value:
                return False
            if self._last_activity_locked(rid) >= older_than:
                return False
            self._append_locked(rid, EventType.RUN_FAILED, payload)
            return True

    async def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_started_at: datetime | None = None,
        before_run_id: str | None = None,
        status: str | None = None,
    ) -> list[RunRecord]:
        rows = [record for record in self._runs.values() if record.user_id == user_id]
        if status:
            rows = [record for record in rows if record.status == status]
        rows.sort(key=lambda record: (record.started_at, record.run_id), reverse=True)
        if before_started_at is not None and before_run_id is not None:
            rows = [
                record
                for record in rows
                if (record.started_at, record.run_id) < (before_started_at, before_run_id)
            ]
        return rows[:limit]

    async def recent_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 3,
        exclude_run_id: str | None = None,
    ) -> list[RunTurn]:
        rows = [
            record
            for record in self._runs.values()
            if record.user_id == user_id
            and record.session_id == session_id
            and record.run_id != exclude_run_id
            and (record.output or "").strip()
        ]
        rows.sort(key=lambda record: (record.started_at, record.run_id), reverse=True)
        newest = rows[:limit]
        newest.reverse()
        return [RunTurn(query=record.input, answer=record.output or "") for record in newest]


async def append_event_in_session(
    session: AsyncSession,
    run_id: str,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    """在调用方的事务里追加一条事件。

    审批决议要把 `approvals.status`、`approval.resolved` 和拒绝/超时的
    `run.failed` 写成一次提交（ADR-0016），所以事件写入必须能挂到外层事务上，
    不能像 `PostgresRunStore.append` 那样自己开事务。
    """
    rid = uuid.UUID(run_id)
    data = payload or {}
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
        RunEventRow(
            run_id=rid,
            seq=seq,
            type=event_type.value,
            payload=data,
            created_at=now,
        )
    )

    patch = build_run_patch(event_type, data, now)
    for name in patch.__dataclass_fields__:
        value = getattr(patch, name)
        if value is not None:
            setattr(row, name, value)
    if event_type is EventType.STEP_COMPLETED:
        # 失败 run 也需要“跑了几步”的口径；run.completed 会覆盖为准确值
        row.step_count += 1

    await session.flush()
    return RunEvent(seq=seq, run_id=str(rid), type=event_type, ts=now, payload=data)


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
        client_msg_id = client_msg_id or None
        if client_msg_id:
            existing = await self.find_by_client_msg_id(user_id, client_msg_id)
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
                    existing = await self.find_by_client_msg_id(user_id, client_msg_id)
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

    async def status(self, run_id: str) -> str | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            return await session.scalar(select(Run.status).where(Run.id == rid))

    async def owner(self, run_id: str) -> str | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            return await session.scalar(select(Run.user_id).where(Run.id == rid))

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        async with self._sessionmaker() as session, session.begin():
            return await append_event_in_session(session, run_id, event_type, payload)

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
        events = [_event_from_row(row) for row in rows]
        return [event for event in events if event is not None]

    async def set_status(self, run_id: str, status: str, *, error_code: str | None = None) -> None:
        rid = uuid.UUID(run_id)
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(Run, rid, with_for_update=True)
            if row is None:
                raise RunNotFoundError(run_id)
            # 不要用断连收尾覆盖已经落库的终态
            if row.status in _TERMINAL_STATUSES:
                return
            row.status = status
            if error_code is not None:
                row.error_code = error_code
                row.failure_category = categorize(error_code).value
            if status in _TERMINAL_STATUSES:
                row.finished_at = datetime.now(UTC)

    async def list_stale_runs(self, *, older_than: datetime, limit: int = 100) -> list[StaleRun]:
        last_event = (
            select(func.max(RunEventRow.created_at))
            .where(RunEventRow.run_id == Run.id)
            .scalar_subquery()
        )
        stmt = (
            select(Run, last_event)
            .where(Run.status == RunStatus.RUNNING.value)
            .where(func.coalesce(last_event, Run.started_at) < older_than)
            .order_by(Run.started_at)
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            StaleRun(
                run_id=str(row.id),
                user_id=row.user_id,
                started_at=row.started_at,
                last_event_at=last or row.started_at,
            )
            for row, last in rows
        ]

    async def fail_stale_run(
        self, run_id: str, *, older_than: datetime, payload: dict[str, Any]
    ) -> bool:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return False
        async with self._sessionmaker() as session, session.begin():
            # 锁住 run 行后再检查：与 append 的 seq 分配同一把锁，
            # 多副本同时回收时只有第一方能迁移到 failed（ADR-0017）
            row = await session.scalar(select(Run).where(Run.id == rid).with_for_update())
            if row is None or row.status != RunStatus.RUNNING.value:
                return False
            last_event = await session.scalar(
                select(func.max(RunEventRow.created_at)).where(RunEventRow.run_id == rid)
            )
            if (last_event or row.started_at) >= older_than:
                return False
            await append_event_in_session(session, run_id, EventType.RUN_FAILED, payload)
            return True

    async def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_started_at: datetime | None = None,
        before_run_id: str | None = None,
        status: str | None = None,
    ) -> list[RunRecord]:
        stmt = select(Run).where(Run.user_id == user_id)
        if status:
            stmt = stmt.where(Run.status == status)
        if before_started_at is not None and before_run_id:
            try:
                before_id = uuid.UUID(before_run_id)
            except ValueError:
                before_id = None
            if before_id is not None:
                stmt = stmt.where(
                    or_(
                        Run.started_at < before_started_at,
                        and_(Run.started_at == before_started_at, Run.id < before_id),
                    )
                )
        stmt = stmt.order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.scalars(stmt)).all()
        return [_record_from_row(row, event_count=0) for row in rows]

    async def recent_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 3,
        exclude_run_id: str | None = None,
    ) -> list[RunTurn]:
        stmt = (
            select(Run.input, Run.output)
            .where(
                Run.user_id == user_id,
                Run.session_id == session_id,
                Run.output.is_not(None),
            )
            # 空串/纯空白等价于没有回答（历史数据里可能有 message.completed 的空文本）。
            # 注意 btrim(output) 默认只去空格，不去换行/制表符；这里用 regexp_replace
            # 去掉所有 \s 再判长度，才和内存实现的 .strip() 同口径
            .where(
                func.length(func.regexp_replace(func.coalesce(Run.output, ""), r"\s", "", "g")) > 0
            )
            .order_by(Run.started_at.desc(), Run.id.desc())
            .limit(limit)
        )
        if exclude_run_id:
            try:
                exclude_id: uuid.UUID | None = uuid.UUID(exclude_run_id)
            except ValueError:
                # 非法 id 不可能命中任何一行，忽略即可（不能让历史读取把本轮打挂）
                exclude_id = None
            if exclude_id is not None:
                stmt = stmt.where(Run.id != exclude_id)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [RunTurn(query=query, answer=answer or "") for query, answer in reversed(rows)]

    async def find_by_client_msg_id(self, user_id: str, client_msg_id: str) -> RunRecord | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(Run).where(
                    Run.user_id == user_id,
                    Run.client_msg_id == client_msg_id,
                )
            )
            if row is None:
                return None
            count = await session.scalar(
                select(func.count()).select_from(RunEventRow).where(RunEventRow.run_id == row.id)
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
        failure_category=row.failure_category,
        started_at=row.started_at,
        finished_at=row.finished_at,
        event_count=event_count,
    )


def _event_from_row(row: RunEventRow) -> RunEvent | None:
    try:
        event_type = EventType(row.type)
    except ValueError:
        # 事件类型只增不改（R1）：旧后端读到新事件时忽略而不是 500
        log.warning(
            "unknown_event_type",
            run_id=str(row.run_id),
            seq=row.seq,
            type=row.type,
        )
        return None
    return RunEvent(
        seq=row.seq,
        run_id=str(row.run_id),
        type=event_type,
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
