"""演示用事件流（W1 D3 骨架）。

真实 Agent 在 W1 D5 之后接入 `graph.py`。这里的目的是先把
「事件流 → SSE → 前端状态机 → 补拉续传」这条链路跑通。

⚠️ 这是脚手架代码，不是业务逻辑。接真实 Agent 时整体删除。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.schemas.event import EventType

Event = tuple[EventType, dict]


async def demo_stream(message: str) -> AsyncIterator[Event]:
    wants_ticket = any(k in message for k in ("开单", "申请", "报修", "审批"))

    yield EventType.RUN_STARTED, {"model": "mock-qwen2.5", "max_steps": 12}
    await asyncio.sleep(0.01)

    # ---- intake ----
    yield EventType.STEP_STARTED, {"node": "intake", "title": "理解问题"}
    await asyncio.sleep(0.01)
    yield EventType.STEP_COMPLETED, {"node": "intake", "duration_ms": 12, "summary": "会话就绪"}

    # ---- classify ----
    yield EventType.STEP_STARTED, {"node": "classify", "title": "判断问题类型"}
    await asyncio.sleep(0.01)
    yield (
        EventType.STEP_COMPLETED,
        {
            "node": "classify",
            "duration_ms": 8,
            "summary": "命中规则：hardware（关键词「打印机」）",
        },
    )

    # ---- 工具：查资产（只读，自动执行）----
    yield (
        EventType.TOOL_CALL,
        {
            "call_id": "call_1",
            "tool": "query_cmdb",
            "args": {"owner_id": "u_102"},
            "write": False,
        },
    )
    await asyncio.sleep(0.02)
    yield (
        EventType.TOOL_RESULT,
        {
            "call_id": "call_1",
            "tool": "query_cmdb",
            "status": "ok",
            "result": {"asset_id": "PC-20481", "model": "ThinkPad T14", "status": "online"},
            "duration_ms": 126,
        },
    )

    # ---- 工具：检索知识库（只读）----
    yield (
        EventType.TOOL_CALL,
        {
            "call_id": "call_2",
            "tool": "search_kb",
            "args": {"query": "打印机 离线 排查"},
            "write": False,
        },
    )
    await asyncio.sleep(0.02)
    yield (
        EventType.TOOL_RESULT,
        {
            "call_id": "call_2",
            "tool": "search_kb",
            "status": "ok",
            "result": {
                "hits": [
                    {"chunk_id": 10231, "score": 0.82},
                    {"chunk_id": 10233, "score": 0.71},
                ]
            },
            "duration_ms": 348,
        },
    )

    citations = [
        {
            "chunk_id": 10231,
            "document_id": "doc_7f2",
            "ord": 4,
            "title": "打印机常见故障排查",
            "heading": "打印机 > 离线排查 > 步骤 3",
            "snippet": "若设备显示离线，先确认是否与电脑处于同一网段…",
            "page": 12,
        },
        {
            "chunk_id": 10233,
            "document_id": "doc_7f2",
            "ord": 6,
            "title": "打印机常见故障排查",
            "heading": "打印机 > 离线排查 > 步骤 5",
            "snippet": "重启打印服务：services.msc → Print Spooler → 重新启动",
            "page": 13,
        },
    ]

    # ---- 写操作：需要人工审批 ----
    if wants_ticket:
        yield (
            EventType.APPROVAL_REQUIRED,
            {
                "approval_id": "apr_demo_1",
                "tool": "create_ticket",
                "args": {
                    "title": "打印机离线无法打印",
                    "category": "hardware",
                    "priority": "P2",
                    "asset_id": "PC-20481",
                },
                "risk_level": "medium",
                "reason": "将在工单系统创建一条记录，影响：IT 服务台派单",
                "expires_at": "2026-11-09T03:00:00Z",
            },
        )
        return

    # ---- 生成 ----
    answer = (
        "你名下的笔记本（PC-20481）在线，问题大概率出在打印机侧。"
        "请按以下顺序排查：1）确认打印机与电脑在同一网段；2）重启 Print Spooler 服务；"
        "3）在设备管理器里移除后重新添加打印机。仍不行我可以帮你开一张工单。"
    )
    yield EventType.STEP_STARTED, {"node": "plan", "title": "组织排查步骤"}
    await asyncio.sleep(0.01)
    yield EventType.STEP_COMPLETED, {"node": "plan", "duration_ms": 640}

    for i in range(0, len(answer), 12):
        yield EventType.MESSAGE_DELTA, {"text": answer[i : i + 12]}
        await asyncio.sleep(0.01)

    yield EventType.MESSAGE_COMPLETED, {"text": answer, "citations": citations}
    yield (
        EventType.RUN_COMPLETED,
        {
            "status": "completed",
            "steps": 6,
            "token_in": 1820,
            "token_out": 310,
            "cost_cents": 3,
            "duration_ms": 1240,
        },
    )
