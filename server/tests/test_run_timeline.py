"""历史会话运行过程投影（ADR-0035）。"""

from __future__ import annotations

from app.runs.timeline import MAX_TIMELINE_ITEMS, build_timeline
from app.schemas.event import EventType, RunEvent


def _event(seq: int, etype: EventType, payload: dict[str, object]) -> RunEvent:
    return RunEvent(seq=seq, run_id="run_1", type=etype, payload=payload)


def test_build_timeline_merges_tool_call_and_result() -> None:
    items, truncated = build_timeline(
        [
            _event(1, EventType.STEP_STARTED, {"node": "act"}),
            _event(
                2,
                EventType.TOOL_CALL,
                {"call_id": "call_1", "tool": "query_cmdb", "args": {}, "write": False},
            ),
            _event(
                3,
                EventType.TOOL_RESULT,
                {
                    "call_id": "call_1",
                    "tool": "query_cmdb",
                    "status": "ok",
                    "result": {"count": 2},
                    "duration_ms": 12,
                    "attempts": 1,
                },
            ),
            _event(4, EventType.STEP_COMPLETED, {"node": "act"}),
        ]
    )

    assert truncated is False
    assert items == [
        {
            "kind": "tool",
            "seq": 2,
            "call_id": "call_1",
            "tool": "query_cmdb",
            "args": {},
            "write": False,
            "status": "ok",
            "result": {"count": 2},
            "duration_ms": 12,
            "attempts": 1,
        }
    ]


def test_build_timeline_merges_approval_and_hides_resolver() -> None:
    items, truncated = build_timeline(
        [
            _event(
                5,
                EventType.APPROVAL_REQUIRED,
                {
                    "approval_id": "apr_1",
                    "tool": "create_ticket",
                    "args": {"title": "打印机报修"},
                    "risk_level": "high",
                    "reason": "将创建工单",
                    "expires_at": "2026-01-01T00:00:00Z",
                },
            ),
            _event(
                6,
                EventType.APPROVAL_RESOLVED,
                {
                    "approval_id": "apr_1",
                    "status": "approved",
                    "resolved_by": "u_205",
                    "reason": "同意",
                    "scope": "once",
                },
            ),
        ]
    )

    assert truncated is False
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "approval"
    assert item["status"] == "approved"
    assert item["decision_reason"] == "同意"
    assert item["resolved_at"].endswith("+00:00")
    # 审批人身份与授权范围属于内部治理信息，不进历史回放
    assert "resolved_by" not in item
    assert "scope" not in item


def test_build_timeline_keeps_pending_approval_and_ignores_orphans() -> None:
    items, _ = build_timeline(
        [
            _event(1, EventType.TOOL_RESULT, {"call_id": "call_missing", "status": "ok"}),
            _event(
                2,
                EventType.APPROVAL_REQUIRED,
                {"approval_id": "apr_1", "tool": "create_ticket", "args": {}},
            ),
            _event(3, EventType.APPROVAL_RESOLVED, {"approval_id": "apr_missing"}),
            _event(4, EventType.TOOL_CALL, {"call_id": "call_x"}),
        ]
    )

    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["risk_level"] == "medium"


def test_build_timeline_truncates_and_tolerates_malformed_payloads() -> None:
    events = [
        _event(
            seq,
            EventType.TOOL_CALL,
            {
                "call_id": f"call_{seq}",
                "tool": "query_cmdb",
                "args": ["not-a-dict"],
                "write": "false",
            },
        )
        for seq in range(1, MAX_TIMELINE_ITEMS + 2)
    ]
    events.append(
        _event(
            99,
            EventType.TOOL_RESULT,
            {
                "call_id": "call_1",
                "status": None,
                "duration_ms": True,
                "attempts": -1,
            },
        )
    )

    items, truncated = build_timeline(events)

    assert truncated is True
    assert len(items) == MAX_TIMELINE_ITEMS
    assert items[0]["args"] == {}
    # 字符串 "false" 不是布尔值，不能被当成写操作
    assert items[0]["write"] is False
    assert items[0]["status"] == "unknown"
    assert "duration_ms" not in items[0]
    assert "attempts" not in items[0]
