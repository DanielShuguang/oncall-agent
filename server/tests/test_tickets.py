"""工单仓储：按 requester 只读查询（ADR-0029）。"""

from __future__ import annotations

import asyncio

from app.tools.tickets import InMemoryTicketRepository


async def test_list_for_requester_only_returns_own_tickets() -> None:
    repo = InMemoryTicketRepository()
    own = await repo.create(
        title="打印机离线", category="hardware", priority="P2", requester="u_102"
    )
    await repo.create(title="VPN 连不上", category="network", priority="P1", requester="u_205")

    rows = await repo.list_for_requester("u_102")
    assert [row["id"] for row in rows] == [own["id"]]
    assert rows[0]["created_at"] is not None


async def test_list_for_requester_is_newest_first_and_limited() -> None:
    repo = InMemoryTicketRepository()
    first = await repo.create(title="第一张", category="hardware", priority="P2", requester="u_102")
    await asyncio.sleep(0.002)
    second = await repo.create(
        title="第二张", category="software", priority="P3", requester="u_102"
    )
    await asyncio.sleep(0.002)
    third = await repo.create(title="第三张", category="network", priority="P1", requester="u_102")

    rows = await repo.list_for_requester("u_102", limit=2)
    assert [row["id"] for row in rows] == [third["id"], second["id"]]
    assert first["id"] not in {row["id"] for row in rows}


async def test_list_for_requester_filters_status() -> None:
    repo = InMemoryTicketRepository()
    open_ticket = await repo.create(
        title="还在处理", category="hardware", priority="P2", requester="u_102"
    )
    resolved = await repo.create(
        title="已经修好", category="hardware", priority="P2", requester="u_102"
    )
    repo._tickets[resolved["id"]]["status"] = "resolved"

    opened = await repo.list_for_requester("u_102", status="open")
    assert [row["id"] for row in opened] == [open_ticket["id"]]
    assert await repo.list_for_requester("u_102", status="closed") == []
