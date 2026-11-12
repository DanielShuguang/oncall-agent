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


async def test_get_for_requester_is_scoped_and_missing_returns_none() -> None:
    repo = InMemoryTicketRepository()
    mine = await repo.create(
        title="打印机离线", category="hardware", priority="P2", requester="u_102"
    )
    other = await repo.create(
        title="VPN 连不上", category="network", priority="P1", requester="u_205"
    )
    # 详情字段来自表里已有的数据；内存仓储创建时显式留空，形状与 PG 一致
    assert mine["description"] is None
    assert mine["assignee"] is None
    repo._tickets[mine["id"]]["description"] = "打印机每次重启后离线"
    repo._tickets[mine["id"]]["assignee"] = "u_902"

    found = await repo.get_for_requester("u_102", mine["id"])
    assert found is not None
    assert found["id"] == mine["id"]
    assert found["description"] == "打印机每次重启后离线"
    assert found["assignee"] == "u_902"
    # 不是本人的单与不存在的单都返回 None，调用方无法区分
    assert await repo.get_for_requester("u_102", other["id"]) is None
    assert await repo.get_for_requester("u_102", "TCK-DEADBEEF") is None
