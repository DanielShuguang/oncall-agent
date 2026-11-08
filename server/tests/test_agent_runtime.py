"""Agent runtime（W1 D5）：事件顺序、工具治理接入、失败语义。

这里直接跑 `runtime.stream()`，不经过 SSE/数据库 —— 事件之外的行为由
`test_chat_stream.py` 覆盖。
"""

from __future__ import annotations

import uuid

from app.agent.runtime import build_deps, stream
from app.schemas.event import EventType
from app.tools.registry import Identity

EMPLOYEE = Identity(user_id="u_102", roles=frozenset({"employee"}))


async def _run(
    query: str,
    *,
    identity: Identity = EMPLOYEE,
    max_steps: int = 12,
    timeout_s: float = 120.0,
) -> list[tuple[EventType, dict[str, object]]]:
    run_id = str(uuid.uuid4())
    return [
        event
        async for event in stream(
            run_id=run_id,
            identity=identity,
            query=query,
            model="test-model",
            max_steps=max_steps,
            timeout_s=timeout_s,
            deps=build_deps(),
        )
    ]


def _of(events: list[tuple[EventType, dict[str, object]]], kind: EventType) -> list[dict]:
    return [payload for etype, payload in events if etype is kind]


async def test_printer_query_executes_cmdb_and_answers() -> None:
    events = await _run("我电脑连不上打印机了")
    types = [etype for etype, _ in events]

    assert types[0] is EventType.RUN_STARTED
    assert types[-1] is EventType.RUN_COMPLETED
    assert EventType.TOOL_CALL in types
    assert EventType.TOOL_RESULT in types

    call = _of(events, EventType.TOOL_CALL)[0]
    assert call["tool"] == "query_cmdb"
    assert call["args"] == {"owner_id": "u_102"}
    assert call["write"] is False

    result = _of(events, EventType.TOOL_RESULT)[0]
    assert result["status"] == "ok"
    assert result["result"]["asset_id"] == "PC-20481"

    completed = _of(events, EventType.RUN_COMPLETED)[0]
    assert completed["status"] == "completed"
    # steps 口径 = 实际走完的节点数，与 step.completed 条数一致
    assert completed["steps"] == len(_of(events, EventType.STEP_COMPLETED))

    answer = _of(events, EventType.MESSAGE_COMPLETED)[0]["text"]
    assert "PC-20481" in answer
    assert "打印机" in answer

    citations = _of(events, EventType.MESSAGE_COMPLETED)[0]["citations"]
    assert len(citations) >= 2
    assert "打印机离线排查指南" in {citation["title"] for citation in citations}


async def test_retrieve_emits_three_vpn_citations() -> None:
    events = await _run("VPN 连不上怎么办")
    citations = _of(events, EventType.MESSAGE_COMPLETED)[0]["citations"]

    assert len(citations) == 3
    assert {citation["title"] for citation in citations} == {"VPN 连接失败排查指南"}
    # 引用必须可定位：chunk_id/document_id/ord 是前端跳原文的三元组
    for citation in citations:
        assert citation["chunk_id"] > 0
        assert citation["document_id"]
        assert citation["ord"] >= 0
        assert citation["snippet"]


async def test_no_retrieval_falls_back_to_refusal() -> None:
    events = await _run("公司年会抽奖规则是什么")
    completed = _of(events, EventType.MESSAGE_COMPLETED)[0]

    assert completed["citations"] == []
    assert "没有检索到" in completed["text"]


async def test_step_events_carry_contract_fields() -> None:
    events = await _run("打印机离线")
    started = _of(events, EventType.STEP_STARTED)
    completed = _of(events, EventType.STEP_COMPLETED)

    assert [s["step"] for s in started] == [1, 2, 3, 4, 5]
    assert [s["node"] for s in started] == [
        "intake",
        "retrieve",
        "plan",
        "act",
        "finalize",
    ]
    for payload in started:
        assert {"step", "node", "title"} <= payload.keys()
    for payload in completed:
        assert {"step", "node", "duration_ms", "summary"} <= payload.keys()


async def test_write_request_requires_approval_instead_of_executing() -> None:
    events = await _run("帮我开一张报修工单")
    types = [etype for etype, _ in events]

    assert types[-1] is EventType.APPROVAL_REQUIRED
    assert EventType.RUN_COMPLETED not in types

    approval = _of(events, EventType.APPROVAL_REQUIRED)[0]
    assert approval["tool"] == "create_ticket"
    assert approval["risk_level"] == "medium"
    assert str(approval["expires_at"]).endswith("Z")
    assert approval["args"]["priority"] == "P2"

    # 写操作只挂起、不执行：tool.result 是 requires_approval，没有 ok
    results = _of(events, EventType.TOOL_RESULT)
    assert results and results[0]["status"] == "requires_approval"


async def test_unrelated_message_skips_tools() -> None:
    events = await _run("你好，今天天气怎么样")
    types = [etype for etype, _ in events]

    assert EventType.TOOL_CALL not in types
    assert types[-1] is EventType.RUN_COMPLETED
    answer = _of(events, EventType.MESSAGE_COMPLETED)[0]["text"]
    assert "工单" in answer


async def test_tool_failure_degrades_but_run_completes() -> None:
    stranger = Identity(user_id="u_none", roles=frozenset({"employee"}))
    events = await _run("打印机连不上", identity=stranger)

    result = _of(events, EventType.TOOL_RESULT)[0]
    assert result["status"] == "error"
    assert result["error_kind"] == "not_found"

    assert [etype for etype, _ in events][-1] is EventType.RUN_COMPLETED
    answer = _of(events, EventType.MESSAGE_COMPLETED)[0]["text"]
    assert "数据可能过期" in answer


async def test_step_limit_fails_run_with_error_code() -> None:
    events = await _run("打印机离线", max_steps=2)
    types = [etype for etype, _ in events]

    assert types[-1] is EventType.RUN_FAILED
    failed = _of(events, EventType.RUN_FAILED)[0]
    assert failed["error_code"] == "STEP_LIMIT"
    assert failed["at_step"] == 3
    assert EventType.RUN_COMPLETED not in types


async def test_run_timeout_fails_before_first_step() -> None:
    events = await _run("打印机离线", timeout_s=0)
    types = [etype for etype, _ in events]

    assert types == [EventType.RUN_STARTED, EventType.RUN_FAILED]
    failed = _of(events, EventType.RUN_FAILED)[0]
    assert failed["error_code"] == "TIMEOUT"
    assert failed["at_step"] == 0
