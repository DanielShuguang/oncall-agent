"""审批存储：内存实现用于测试，Postgres 实现用于真实运行。

状态迁移必须在存储层原子完成（`WHERE status='pending'`），否则两个审批人
同时点通过会各自执行一次写工具 —— 审批的全部意义就是"只执行一次"。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.approvals.types import ApprovalRecord
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
        limit: int = 100,
    ) -> list[ApprovalRecord]: ...

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
        内存实现没有事务，回调收到 `None`，由服务层直接写事件。
        """
        ...

    async def is_granted(
        self, *, user_id: str, session_id: str, tool_name: str, at: datetime
    ) -> bool: ...


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
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        items = [
            record
            for record in self._records.values()
            if (status is None or record.status == status)
            and (requested_by is None or record.requested_by == requested_by)
        ]
        items.sort(key=lambda r: (r.status != "pending", r.expires_at, r.created_at))
        return items[:limit]

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
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        query = select(Approval)
        if status is not None:
            query = query.where(Approval.status == status)
        if requested_by is not None:
            query = query.where(Approval.requested_by == requested_by)
        query = query.order_by(Approval.expires_at, Approval.created_at).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.scalars(query)).all()
        return [_record_from_row(row) for row in rows]

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
