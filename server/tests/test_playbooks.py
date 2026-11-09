"""W3 D15：三条剧本连续演示（不重启进程、不重建 store）。"""

from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient

from app.schemas.event import EventType
from app.tools.tickets import InMemoryTicketRepository
from tests.support import auth_headers

EMPLOYEE = auth_headers("u_102", ("employee",))
APPROVER = auth_headers("u_900", ("approver",))


def _parse(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


async def _run(client: AsyncClient, message: str, *, session_id: str) -> list[dict[str, Any]]:
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"session_id": session_id, "message": message},
        headers=EMPLOYEE,
    ) as res:
        assert res.status_code == 200
        lines = [line async for line in res.aiter_lines()]
    return _parse(lines)


def _types(events: list[dict[str, Any]]) -> list[str]:
    return [str(event["type"]) for event in events]


async def test_three_playbooks_run_back_to_back(
    client: AsyncClient, mem_tickets: InMemoryTicketRepository
) -> None:
    # ① 打印机离线：查资产 + 检索 + 只读建议，无写操作
    printer = await _run(client, "我电脑连不上打印机了", session_id="sess_p1")
    assert printer[-1]["type"] == EventType.RUN_COMPLETED.value
    assert any(
        e["type"] == EventType.TOOL_RESULT.value and e["payload"]["status"] == "ok" for e in printer
    )
    assert EventType.APPROVAL_REQUIRED.value not in _types(printer)
    answer = next(e for e in printer if e["type"] == EventType.MESSAGE_COMPLETED.value)
    assert "PC-20481" in answer["payload"]["text"]
    assert answer["payload"]["citations"]

    # ② 申请权限：检索政策 → 写操作挂起 → 人工批准 → 工单落库
    apply = await _run(client, "帮我申请开通 VPN 权限", session_id="sess_p2")
    approval = next(e for e in apply if e["type"] == EventType.APPROVAL_REQUIRED.value)
    assert approval["payload"]["tool"] == "create_ticket"
    assert mem_tickets.count() == 0

    resolved = await client.post(
        f"/api/approvals/{approval['payload']['approval_id']}/resolve",
        json={"decision": "approved", "reason": "已核对权限政策"},
        headers=APPROVER,
    )
    assert resolved.status_code == 200
    assert resolved.json()["run_status"] == "completed"
    assert mem_tickets.count() == 1

    # ③ 知识问答：纯 RAG，带引用
    vpn = await _run(client, "VPN 连不上怎么办", session_id="sess_p3")
    assert vpn[-1]["type"] == EventType.RUN_COMPLETED.value
    assert EventType.TOOL_CALL.value not in _types(vpn)
    citations = next(e for e in vpn if e["type"] == EventType.MESSAGE_COMPLETED.value)["payload"][
        "citations"
    ]
    assert len(citations) == 3
    assert {c["title"] for c in citations} == {"VPN 连接失败排查指南"}
