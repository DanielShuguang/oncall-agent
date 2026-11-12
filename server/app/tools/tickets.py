"""工单仓储：工具 handler 做业务写入，SQL 只出现在这里。

W3 的 `create_ticket` 在审批通过后真正落库（模拟 IT 服务台，docs/02 §2.7）。
内存实现用于测试与无库演示；Postgres 实现写 `tickets` 表。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select

from app.models.business import Ticket

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings


class TicketRepository(Protocol):
    async def create(
        self,
        *,
        title: str,
        category: str,
        priority: str,
        requester: str,
        asset_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def get(self, ticket_id: str) -> dict[str, Any] | None: ...

    async def get_for_requester(self, requester: str, ticket_id: str) -> dict[str, Any] | None:
        """按单号查某人自己的工单；不是本人的单返回 None，不泄露存在性。"""
        ...

    async def list_for_requester(
        self, requester: str, *, status: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """查某人自己的工单，按创建时间倒序；只读，不返回别人的工单。"""
        ...


def _new_ticket_id() -> str:
    return f"TCK-{uuid.uuid4().hex[:8].upper()}"


class InMemoryTicketRepository:
    def __init__(self) -> None:
        self._tickets: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        title: str,
        category: str,
        priority: str,
        requester: str,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        ticket: dict[str, Any] = {
            "id": _new_ticket_id(),
            "title": title,
            "description": None,
            "category": category,
            "priority": priority,
            "status": "open",
            "requester": requester,
            "assignee": None,
            "asset_id": asset_id,
            "created_at": datetime.now(UTC).isoformat(),
            "resolved_at": None,
        }
        async with self._lock:
            self._tickets[ticket["id"]] = ticket
        return dict(ticket)

    async def get(self, ticket_id: str) -> dict[str, Any] | None:
        ticket = self._tickets.get(ticket_id)
        return dict(ticket) if ticket is not None else None

    async def get_for_requester(self, requester: str, ticket_id: str) -> dict[str, Any] | None:
        async with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None or ticket["requester"] != requester:
                return None
            return dict(ticket)

    async def list_for_requester(
        self, requester: str, *, status: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        async with self._lock:
            rows = [
                ticket
                for ticket in self._tickets.values()
                if ticket["requester"] == requester
                and (status is None or ticket["status"] == status)
            ]
        # ISO-8601 UTC 字符串可直接按字典序倒排；id 兜底保证同一微秒内顺序稳定
        rows.sort(key=lambda ticket: (ticket["created_at"], ticket["id"]), reverse=True)
        return [dict(ticket) for ticket in rows[:limit]]

    def count(self) -> int:
        return len(self._tickets)


class PostgresTicketRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        title: str,
        category: str,
        priority: str,
        requester: str,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        row = Ticket(
            id=_new_ticket_id(),
            title=title,
            category=category,
            priority=priority,
            status="open",
            requester=requester,
            asset_id=asset_id,
        )
        async with self._sessionmaker() as session, session.begin():
            session.add(row)
        return _ticket_dict(row)

    async def get(self, ticket_id: str) -> dict[str, Any] | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(select(Ticket).where(Ticket.id == ticket_id))
        return _ticket_dict(row) if row is not None else None

    async def get_for_requester(self, requester: str, ticket_id: str) -> dict[str, Any] | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(Ticket).where(
                    Ticket.id == ticket_id,
                    Ticket.requester == requester,
                )
            )
        return _ticket_dict(row) if row is not None else None

    async def list_for_requester(
        self, requester: str, *, status: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        query = select(Ticket).where(Ticket.requester == requester)
        if status is not None:
            query = query.where(Ticket.status == status)
        query = query.order_by(Ticket.created_at.desc(), Ticket.id.desc()).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.scalars(query)).all()
        return [_ticket_dict(row) for row in rows]


def _ticket_dict(row: Ticket) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description,
        "category": row.category,
        "priority": row.priority,
        "status": row.status,
        "requester": row.requester,
        "assignee": row.assignee,
        "asset_id": row.asset_id,
        "created_at": row.created_at.isoformat() if row.created_at is not None else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at is not None else None,
    }


_repository: TicketRepository | None = None


def build_ticket_repository(settings: Settings) -> TicketRepository:
    if settings.store_backend == "memory":
        return InMemoryTicketRepository()
    from app.core.db import get_sessionmaker

    return PostgresTicketRepository(get_sessionmaker())


def get_ticket_repository() -> TicketRepository:
    global _repository
    if _repository is None:
        from app.core.config import get_settings

        _repository = build_ticket_repository(get_settings())
    return _repository


def set_ticket_repository(value: TicketRepository | None) -> None:
    global _repository
    _repository = value
