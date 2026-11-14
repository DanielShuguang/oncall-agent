"""审批存储：内存实现用于测试，Postgres 实现用于真实运行。

状态迁移必须在存储层原子完成（`WHERE status='pending'`），否则两个审批人
同时点通过会各自执行一次写工具 —— 审批的全部意义就是"只执行一次"。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy import and_, delete, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.elements import ColumnElement

from app.approvals.types import (
    MAX_STATS_GROUPS,
    ApprovalDayStats,
    ApprovalGroupBy,
    ApprovalGroupStats,
    ApprovalHourStats,
    ApprovalInvalidCursor,
    ApprovalListCursor,
    ApprovalListFilters,
    ApprovalRecord,
    ApprovalStats,
    PendingApprovalCursor,
    ResolvedApprovalCursor,
)
from app.models.approval import Approval, ApprovalGrant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings

#: 决议状态迁移成功后的回调；参数是当前事务的 session（内存实现传 None）。
#: 审批服务用它把 `approval.resolved` / `run.failed` 写进同一个事务（ADR-0016）。
OnResolved = Callable[[Any], Awaitable[None]]


class ApprovalStore(Protocol):
    async def create(self, record: ApprovalRecord) -> ApprovalRecord: ...

    async def get(self, approval_id: str) -> ApprovalRecord | None: ...

    async def find_pending(self, *, run_id: str, tool_name: str) -> ApprovalRecord | None: ...

    async def list(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        filters: ApprovalListFilters | None = None,
        cursor: ApprovalListCursor | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        """按 status 选择排序键的 keyset 翻页（ADR-0052 / ADR-0053 / ADR-0054）。

        待办（`status="pending"` 或 `None`）按 `(expires_at, created_at, id)`
        升序，最急的在前；已办按 `(resolved_at, id)` 倒序，最近的决议在前。
        `filters` 只作用于已办：工具/审批人精确匹配，决议时间半开区间。
        游标只配合同一个 `status` 和同一组筛选条件使用，跨状态/跨筛选复用
        会从错误的元组位置开始，结果不可解释。
        """
        ...

    async def count(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        filters: ApprovalListFilters | None = None,
    ) -> int:
        """与 `list` 同一 status/身份/筛选口径的计数（ADR-0057）。

        不受游标影响；API 只在第一页调用，用于「共 N 条」。已办仍要求
        `resolved_at` 非空，避免脏数据让计数与列表不一致。
        """
        ...

    async def stats(
        self,
        *,
        since: datetime,
        now: datetime,
        group_by: ApprovalGroupBy | None = None,
    ) -> ApprovalStats:
        """当前未过期待办与窗口内决议等待（ADR-0048/0051）。

        `group_by` 只聚合已决议审批：待办没有审批人归属，不能按 `resolved_by`
        分组；各分组之和等于 `decided_count`。返回最多 `MAX_STATS_GROUPS` 组。
        """
        ...

    async def resolve(
        self,
        approval_id: str,
        *,
        status: str,
        resolved_by: str,
        reason: str | None,
        scope: str,
        at: datetime,
        grant_until: datetime | None = None,
        on_resolved: OnResolved | None = None,
    ) -> tuple[ApprovalRecord | None, bool]:
        """原子迁移 pending→status。

        返回 `(迁移后的记录, 本次是否真的迁移)`；并发点击时只有一方拿到 True，
        另一方拿到已有决议且不会重复执行工具。

        `on_resolved` 只在本次真的迁移后调用：Postgres 实现在同一事务内、
        提交前调用（回调收到 `AsyncSession`），回调抛异常则决议一起回滚；
        内存实现没有事务，回调收到 `None`，由服务层直接写事件。内存实现
        回调失败时不会回滚已迁移状态/已写事件，只用于测试与显式内存后端。
        """
        ...

    async def is_granted(
        self, *, user_id: str, session_id: str, tool_name: str, at: datetime
    ) -> bool: ...

    async def prune_snapshots(
        self,
        *,
        resolved_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> int:
        """清空已决议且早于阈值的 `state`，返回涉及条数（ADR-0027）。

        只清非 pending 的行：挂起的审批还要靠快照恢复执行。清空后 `state` 是空对象，
        它本身就是「已回收」的标记——合法快照至少带 `run_id` / `node`，不会是 `{}`，
        因此不需要再加一列（迁移 0013 之后没有 0014）。决议证据（`args` / `reason` /
        `resolved_by` / `resolved_at` / `status`）保留。`dry_run` 只计数。
        """
        ...

    async def prune_grants(
        self,
        *,
        expired_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> int:
        """删除 `expires_at` 早于阈值的授权，返回条数（ADR-0027）。

        过期授权不再授予任何权限（`is_granted` 比的是 `expires_at > at`），删行不改变
        授权语义；「谁在哪个会话授过权，授权了什么工具」仍在 `approvals` 里
        （`scope='session'` 的决议行 + `approval.resolved` 事件）。
        """
        ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._grants: dict[tuple[str, str, str], datetime] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: ApprovalRecord) -> ApprovalRecord:
        async with self._lock:
            self._records[record.id] = record
            return record

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        return self._records.get(approval_id)

    async def find_pending(self, *, run_id: str, tool_name: str) -> ApprovalRecord | None:
        for record in self._records.values():
            if record.run_id == run_id and record.tool_name == tool_name and record.is_pending:
                return record
        return None

    async def list(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        filters: ApprovalListFilters | None = None,
        cursor: ApprovalListCursor | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        active_filters = filters or ApprovalListFilters()
        items = [
            record
            for record in self._records.values()
            if (status is None or record.status == status)
            and (requested_by is None or record.requested_by == requested_by)
        ]
        if status is None or status == "pending":
            # 待办按到期紧迫度：最急的在前（ADR-0052）。
            items.sort(key=lambda r: (r.expires_at, r.created_at, r.id))
            if isinstance(cursor, PendingApprovalCursor):
                pending_key = (cursor.expires_at, cursor.created_at, cursor.approval_id)
                items = [
                    record
                    for record in items
                    if (record.expires_at, record.created_at, record.id) > pending_key
                ]
            return items[:limit]

        # 已办按决议时间倒序：最近处理的在前（ADR-0053）。expired 也有
        # resolved_at（expire_due 写入），所以四类状态都能落在这个全序里。
        decided = [
            record
            for record in items
            if record.resolved_at is not None
            and active_filters.matches(
                tool_name=record.tool_name,
                resolved_by=record.resolved_by,
                resolved_at=record.resolved_at,
            )
        ]
        decided.sort(key=lambda r: (cast(datetime, r.resolved_at), r.id), reverse=True)
        if isinstance(cursor, ResolvedApprovalCursor):
            resolved_key = (cursor.resolved_at, cursor.approval_id)
            decided = [
                record
                for record in decided
                if (cast(datetime, record.resolved_at), record.id) < resolved_key
            ]
        return decided[:limit]

    async def count(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        filters: ApprovalListFilters | None = None,
    ) -> int:
        active_filters = filters or ApprovalListFilters()
        total = 0
        for record in self._records.values():
            if status is not None and record.status != status:
                continue
            if requested_by is not None and record.requested_by != requested_by:
                continue
            # 与 list 一致：筛选只作用于已办；待办带筛选由 API 拒绝。
            if (
                status is not None
                and status != "pending"
                and (
                    record.resolved_at is None
                    or not active_filters.matches(
                        tool_name=record.tool_name,
                        resolved_by=record.resolved_by,
                        resolved_at=record.resolved_at,
                    )
                )
            ):
                continue
            total += 1
        return total

    async def stats(
        self,
        *,
        since: datetime,
        now: datetime,
        group_by: ApprovalGroupBy | None = None,
    ) -> ApprovalStats:
        # 已过期但 expire_due 还没收敛到的单不算积压：它们不该再占用审批人注意力。
        pending = [
            record
            for record in self._records.values()
            if record.is_pending and record.expires_at > now
        ]
        oldest_age: int | None = None
        if pending:
            oldest = min(record.created_at for record in pending)
            oldest_age = max(0, int((now - oldest).total_seconds()))
        waits: list[int] = []
        per_day: dict[date, list[int]] = {}
        per_hour: dict[int, list[int]] = {}
        for record in self._records.values():
            if record.status not in ("approved", "rejected"):
                continue
            if record.resolved_at is None or record.resolved_at < since:
                continue
            waited_ms = max(0, int((record.resolved_at - record.created_at).total_seconds() * 1000))
            waits.append(waited_ms)
            per_day.setdefault(record.resolved_at.date(), []).append(waited_ms)
            per_hour.setdefault(record.resolved_at.hour, []).append(waited_ms)
        daily = tuple(
            ApprovalDayStats(
                day=day,
                decided_count=len(waited),
                avg_wait_ms=round(sum(waited) / len(waited)),
            )
            for day, waited in sorted(per_day.items())
        )
        hourly = tuple(
            ApprovalHourStats(
                hour=hour,
                decided_count=len(waited),
                avg_wait_ms=round(sum(waited) / len(waited)),
            )
            for hour, waited in sorted(per_hour.items())
        )
        groups: tuple[ApprovalGroupStats, ...] = ()
        groups_truncated = False
        if group_by is not None:
            per_group: dict[str, list[int]] = {}
            for record in self._records.values():
                if record.status not in ("approved", "rejected"):
                    continue
                if record.resolved_at is None or record.resolved_at < since:
                    continue
                key = record.tool_name if group_by == "tool" else (record.resolved_by or "unknown")
                waited_ms = max(
                    0, int((record.resolved_at - record.created_at).total_seconds() * 1000)
                )
                per_group.setdefault(key, []).append(waited_ms)
            ordered = sorted(per_group.items(), key=lambda item: (-len(item[1]), item[0]))
            groups_truncated = len(ordered) > MAX_STATS_GROUPS
            groups = tuple(
                ApprovalGroupStats(
                    key=key,
                    decided_count=len(waited),
                    avg_wait_ms=round(sum(waited) / len(waited)),
                    max_wait_ms=max(waited),
                )
                for key, waited in ordered[:MAX_STATS_GROUPS]
            )
        return ApprovalStats(
            pending_count=len(pending),
            oldest_pending_age_s=oldest_age,
            decided_count=len(waits),
            avg_wait_ms=round(sum(waits) / len(waits)) if waits else None,
            max_wait_ms=max(waits) if waits else None,
            daily=daily,
            hourly=hourly,
            groups=groups,
            groups_truncated=groups_truncated,
        )

    async def resolve(
        self,
        approval_id: str,
        *,
        status: str,
        resolved_by: str,
        reason: str | None,
        scope: str,
        at: datetime,
        grant_until: datetime | None = None,
        on_resolved: OnResolved | None = None,
    ) -> tuple[ApprovalRecord | None, bool]:
        async with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                return None, False
            if record.status != "pending":
                return record, False
            updated = replace(
                record,
                status=status,
                resolved_by=resolved_by,
                reason=reason,
                scope=scope,
                resolved_at=at,
            )
            self._records[approval_id] = updated
            if (
                status == "approved"
                and scope == "session"
                and updated.session_id
                and grant_until is not None
            ):
                self._grants[(updated.requested_by, updated.session_id, updated.tool_name)] = (
                    grant_until
                )
            if on_resolved is not None:
                await on_resolved(None)
            return updated, True

    async def is_granted(
        self, *, user_id: str, session_id: str, tool_name: str, at: datetime
    ) -> bool:
        expires = self._grants.get((user_id, session_id, tool_name))
        return expires is not None and expires > at

    async def prune_snapshots(
        self,
        *,
        resolved_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> int:
        async with self._lock:
            candidates = sorted(
                (
                    record
                    for record in self._records.values()
                    if not record.is_pending
                    and record.state
                    and record.resolved_at is not None
                    and record.resolved_at < resolved_before
                ),
                key=lambda record: (record.resolved_at or record.created_at, record.id),
            )[:limit]
            if not dry_run:
                for record in candidates:
                    self._records[record.id] = replace(record, state={})
            return len(candidates)

    async def prune_grants(
        self,
        *,
        expired_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> int:
        async with self._lock:
            candidates = sorted(
                (
                    (key, expires)
                    for key, expires in self._grants.items()
                    if expires < expired_before
                ),
                key=lambda item: (item[1], item[0]),
            )[:limit]
            if not dry_run:
                for key, _ in candidates:
                    del self._grants[key]
            return len(candidates)


def _resolved_filter_conditions(filters: ApprovalListFilters) -> list[ColumnElement[bool]]:
    """已办筛选的 SQL 条件；列表与计数共用，避免两边口径漂移（ADR-0057）。"""
    conditions: list[ColumnElement[bool]] = []
    if filters.tool_name is not None:
        conditions.append(Approval.tool_name == filters.tool_name)
    if filters.resolved_by is not None:
        conditions.append(Approval.resolved_by == filters.resolved_by)
    if filters.resolved_from is not None:
        conditions.append(Approval.resolved_at >= filters.resolved_from)
    if filters.resolved_to is not None:
        conditions.append(Approval.resolved_at < filters.resolved_to)
    return conditions


class PostgresApprovalStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, record: ApprovalRecord) -> ApprovalRecord:
        row = Approval(
            id=uuid.UUID(record.id),
            run_id=uuid.UUID(record.run_id),
            call_id=record.call_id,
            session_id=record.session_id,
            tool_name=record.tool_name,
            args=dict(record.args),
            risk_level=record.risk_level,
            status=record.status,
            requested_by=record.requested_by,
            expires_at=record.expires_at,
            created_at=record.created_at,
            state=dict(record.state),
        )
        async with self._sessionmaker() as session, session.begin():
            session.add(row)
        return record

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        try:
            aid = uuid.UUID(approval_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            row = await session.get(Approval, aid)
        return _record_from_row(row) if row is not None else None

    async def find_pending(self, *, run_id: str, tool_name: str) -> ApprovalRecord | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(Approval).where(
                    Approval.run_id == rid,
                    Approval.tool_name == tool_name,
                    Approval.status == "pending",
                )
            )
        return _record_from_row(row) if row is not None else None

    async def list(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        filters: ApprovalListFilters | None = None,
        cursor: ApprovalListCursor | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        active_filters = filters or ApprovalListFilters()
        if cursor is not None:
            # 内存实现允许任意字符串 id（测试用 a1/f1），Postgres 的 approvals.id
            # 是 UUID；伪造游标要在进查询前翻译成 400，不能让 asyncpg 把它变成 503。
            try:
                uuid.UUID(cursor.approval_id)
            except ValueError as exc:
                raise ApprovalInvalidCursor("cursor approval id is not a UUID") from exc
        query = select(Approval)
        if status is not None:
            query = query.where(Approval.status == status)
        if requested_by is not None:
            query = query.where(Approval.requested_by == requested_by)
        if status is None or status == "pending":
            if isinstance(cursor, PendingApprovalCursor):
                query = query.where(
                    or_(
                        Approval.expires_at > cursor.expires_at,
                        and_(
                            Approval.expires_at == cursor.expires_at,
                            Approval.created_at > cursor.created_at,
                        ),
                        and_(
                            Approval.expires_at == cursor.expires_at,
                            Approval.created_at == cursor.created_at,
                            Approval.id > cursor.approval_id,
                        ),
                    )
                )
            query = query.order_by(Approval.expires_at, Approval.created_at, Approval.id)
        else:
            # 已办按决议时间倒序；resolved_at 为空的行只可能是 pending，已在
            # status 过滤时排除，这里再加一次是防脏数据混进来（ADR-0053）。
            query = query.where(Approval.resolved_at.is_not(None))
            for condition in _resolved_filter_conditions(active_filters):
                query = query.where(condition)
            if isinstance(cursor, ResolvedApprovalCursor):
                query = query.where(
                    or_(
                        Approval.resolved_at < cursor.resolved_at,
                        and_(
                            Approval.resolved_at == cursor.resolved_at,
                            Approval.id < cursor.approval_id,
                        ),
                    )
                )
            query = query.order_by(Approval.resolved_at.desc(), Approval.id.desc())
        query = query.limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.scalars(query)).all()
        return [_record_from_row(row) for row in rows]

    async def count(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        filters: ApprovalListFilters | None = None,
    ) -> int:
        active_filters = filters or ApprovalListFilters()
        query = select(func.count(Approval.id))
        if status is not None:
            query = query.where(Approval.status == status)
        if requested_by is not None:
            query = query.where(Approval.requested_by == requested_by)
        if status is not None and status != "pending":
            query = query.where(Approval.resolved_at.is_not(None))
            for condition in _resolved_filter_conditions(active_filters):
                query = query.where(condition)
        async with self._sessionmaker() as session:
            return int((await session.scalar(query)) or 0)

    async def stats(
        self,
        *,
        since: datetime,
        now: datetime,
        group_by: ApprovalGroupBy | None = None,
    ) -> ApprovalStats:
        # 内存实现把负等待夹到 0；PG 也必须一致，否则脏数据会让 avg/max 变负。
        wait_seconds = func.greatest(
            func.extract("epoch", Approval.resolved_at - Approval.created_at), 0
        )
        async with self._sessionmaker() as session:
            pending_row = (
                await session.execute(
                    select(func.count(Approval.id), func.min(Approval.created_at)).where(
                        Approval.status == "pending",
                        # 与内存实现一致：已过期待办不计入积压，即使 expire_due
                        # 因单轮上限还没扫到它。
                        Approval.expires_at > now,
                    )
                )
            ).one()
            decided_row = (
                await session.execute(
                    select(
                        func.count(Approval.id),
                        func.avg(wait_seconds * 1000),
                        func.max(wait_seconds * 1000),
                    ).where(
                        Approval.status.in_(("approved", "rejected")),
                        Approval.resolved_at.is_not(None),
                        Approval.resolved_at >= since,
                    )
                )
            ).one()
            # date_trunc 对 timestamptz 使用会话时区；先转 UTC，保证分桶与文档口径一致（R6）。
            day_column = func.date_trunc("day", func.timezone("UTC", Approval.resolved_at))
            daily_rows = (
                await session.execute(
                    select(
                        day_column,
                        func.count(Approval.id),
                        func.avg(wait_seconds * 1000),
                    )
                    .where(
                        Approval.status.in_(("approved", "rejected")),
                        Approval.resolved_at.is_not(None),
                        Approval.resolved_at >= since,
                    )
                    .group_by(day_column)
                    .order_by(day_column)
                )
            ).all()
            # 小时也按 UTC 归桶；`date_part` 返回 numeric，Python 侧再取整。
            hour_column = func.date_part("hour", func.timezone("UTC", Approval.resolved_at))
            hourly_rows = (
                await session.execute(
                    select(
                        hour_column,
                        func.count(Approval.id),
                        func.avg(wait_seconds * 1000),
                    )
                    .where(
                        Approval.status.in_(("approved", "rejected")),
                        Approval.resolved_at.is_not(None),
                        Approval.resolved_at >= since,
                    )
                    .group_by(hour_column)
                    .order_by(hour_column)
                )
            ).all()
            group_rows: Sequence[Any] = ()
            groups_truncated = False
            if group_by is not None:
                group_column = (
                    Approval.tool_name
                    if group_by == "tool"
                    else func.coalesce(Approval.resolved_by, "unknown")
                )
                group_rows = (
                    await session.execute(
                        select(
                            group_column,
                            func.count(Approval.id),
                            func.avg(wait_seconds * 1000),
                            func.max(wait_seconds * 1000),
                        )
                        .where(
                            Approval.status.in_(("approved", "rejected")),
                            Approval.resolved_at.is_not(None),
                            Approval.resolved_at >= since,
                        )
                        .group_by(group_column)
                        .order_by(func.count(Approval.id).desc(), group_column.asc())
                        .limit(MAX_STATS_GROUPS + 1)
                    )
                ).all()
                groups_truncated = len(group_rows) > MAX_STATS_GROUPS
        pending_count = int(pending_row[0] or 0)
        oldest = pending_row[1]
        decided_count = int(decided_row[0] or 0)
        daily = tuple(
            ApprovalDayStats(
                day=row[0].date(),
                decided_count=int(row[1]),
                avg_wait_ms=(round(float(row[2])) if row[2] is not None else None),
            )
            for row in daily_rows
        )
        hourly = tuple(
            ApprovalHourStats(
                hour=int(row[0]),
                decided_count=int(row[1]),
                avg_wait_ms=(round(float(row[2])) if row[2] is not None else None),
            )
            for row in hourly_rows
        )
        groups = tuple(
            ApprovalGroupStats(
                key=str(row[0]),
                decided_count=int(row[1]),
                avg_wait_ms=(round(float(row[2])) if row[2] is not None else None),
                max_wait_ms=(round(float(row[3])) if row[3] is not None else None),
            )
            for row in group_rows[:MAX_STATS_GROUPS]
        )
        return ApprovalStats(
            pending_count=pending_count,
            oldest_pending_age_s=(
                max(0, int((now - oldest).total_seconds())) if oldest is not None else None
            ),
            decided_count=decided_count,
            avg_wait_ms=(round(float(decided_row[1])) if decided_row[1] is not None else None),
            max_wait_ms=(round(float(decided_row[2])) if decided_row[2] is not None else None),
            daily=daily,
            hourly=hourly,
            groups=groups,
            groups_truncated=groups_truncated,
        )

    async def resolve(
        self,
        approval_id: str,
        *,
        status: str,
        resolved_by: str,
        reason: str | None,
        scope: str,
        at: datetime,
        grant_until: datetime | None = None,
        on_resolved: OnResolved | None = None,
    ) -> tuple[ApprovalRecord | None, bool]:
        try:
            aid = uuid.UUID(approval_id)
        except ValueError:
            return None, False

        async with self._sessionmaker() as session, session.begin():
            row = await session.scalar(select(Approval).where(Approval.id == aid).with_for_update())
            if row is None:
                return None, False
            if row.status != "pending":
                return _record_from_row(row), False

            row.status = status
            row.resolved_by = resolved_by
            row.reason = reason
            row.scope = scope
            row.resolved_at = at

            if (
                status == "approved"
                and scope == "session"
                and row.session_id
                and grant_until is not None
            ):
                stmt = pg_insert(ApprovalGrant).values(
                    user_id=row.requested_by,
                    session_id=row.session_id,
                    tool_name=row.tool_name,
                    granted_by=resolved_by,
                    expires_at=grant_until,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["user_id", "session_id", "tool_name"],
                    set_={"granted_by": resolved_by, "expires_at": grant_until},
                )
                await session.execute(stmt)
            await session.flush()
            record = _record_from_row(row)
            if on_resolved is not None:
                # 与状态迁移同一事务：事件写失败则决议回滚，不会留下
                # “已通过但没有 approval.resolved”的半截状态（ADR-0016）
                await on_resolved(session)
            return record, True

    async def is_granted(
        self, *, user_id: str, session_id: str, tool_name: str, at: datetime
    ) -> bool:
        async with self._sessionmaker() as session:
            expires = await session.scalar(
                select(ApprovalGrant.expires_at).where(
                    ApprovalGrant.user_id == user_id,
                    ApprovalGrant.session_id == session_id,
                    ApprovalGrant.tool_name == tool_name,
                )
            )
        return expires is not None and expires > at

    async def prune_snapshots(
        self,
        *,
        resolved_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> int:
        stmt = (
            select(Approval.id)
            .where(
                Approval.status != "pending",
                Approval.resolved_at.is_not(None),
                Approval.resolved_at < resolved_before,
                # 空对象不是合法快照，清过的行不会再被选中（幂等，无需标记列）
                Approval.state != text("'{}'::jsonb"),
            )
            .order_by(Approval.resolved_at)
            .limit(limit)
        )
        if dry_run:
            async with self._sessionmaker() as session:
                return len((await session.scalars(stmt)).all())

        async with self._sessionmaker() as session, session.begin():
            # SKIP LOCKED：多副本各清各的批次，不互相等待
            ids = (await session.scalars(stmt.with_for_update(skip_locked=True))).all()
            if not ids:
                return 0
            await session.execute(update(Approval).where(Approval.id.in_(ids)).values(state={}))
        return len(ids)

    async def prune_grants(
        self,
        *,
        expired_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> int:
        stmt = (
            select(ApprovalGrant.user_id, ApprovalGrant.session_id, ApprovalGrant.tool_name)
            .where(ApprovalGrant.expires_at < expired_before)
            .order_by(ApprovalGrant.expires_at)
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            if dry_run:
                return len((await session.execute(stmt)).all())
            async with session.begin():
                rows = (await session.execute(stmt.with_for_update(skip_locked=True))).all()
                if not rows:
                    return 0
                await session.execute(
                    delete(ApprovalGrant).where(
                        tuple_(
                            ApprovalGrant.user_id,
                            ApprovalGrant.session_id,
                            ApprovalGrant.tool_name,
                        ).in_([tuple(row) for row in rows])
                    )
                )
        return len(rows)


def _record_from_row(row: Approval) -> ApprovalRecord:
    return ApprovalRecord(
        id=str(row.id),
        run_id=str(row.run_id),
        call_id=row.call_id,
        tool_name=row.tool_name,
        args=dict(row.args or {}),
        risk_level=row.risk_level,
        status=row.status,
        requested_by=row.requested_by,
        expires_at=row.expires_at,
        created_at=row.created_at,
        resolved_by=row.resolved_by,
        reason=row.reason,
        scope=row.scope,
        session_id=row.session_id,
        resolved_at=row.resolved_at,
        state=dict(row.state or {}),
    )


_approval_store: ApprovalStore | None = None


def build_approval_store(settings: Settings) -> ApprovalStore:
    if settings.store_backend == "memory":
        return InMemoryApprovalStore()
    from app.core.db import get_sessionmaker

    return PostgresApprovalStore(get_sessionmaker())


def get_approval_store() -> ApprovalStore:
    """FastAPI 依赖；测试用 `dependency_overrides` 换成内存实现。"""
    global _approval_store
    if _approval_store is None:
        from app.core.config import get_settings

        _approval_store = build_approval_store(get_settings())
    return _approval_store


def set_approval_store(value: ApprovalStore | None) -> None:
    global _approval_store
    _approval_store = value
