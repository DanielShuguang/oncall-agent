"""审批闭环（W3 D14）：挂起 → 审批 → 恢复执行 → 工单落库。

覆盖 docs/06 §7 的关键语义：不能自批、幂等、超时、scope=session。
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.approvals.service import ApprovalService
from app.approvals.store import InMemoryApprovalStore
from app.approvals.types import (
    ApprovalInvalidCursor,
    ApprovalListFilters,
    ApprovalNotReady,
    ApprovalRecord,
    PendingApprovalCursor,
    ResolvedApprovalCursor,
)
from app.core.store import InMemoryRunStore
from app.schemas.event import EventType
from app.tools.registry import Identity
from app.tools.tickets import InMemoryTicketRepository
from tests.support import auth_headers

EMPLOYEE = auth_headers("u_102", ("employee",))
APPROVER = auth_headers("u_900", ("approver",))
SELF_APPROVER = auth_headers("u_102", ("employee", "approver"))


def _parse(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


async def _stream(
    client: AsyncClient,
    message: str,
    *,
    session_id: str = "sess_approval",
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"session_id": session_id, "message": message},
        headers=headers or EMPLOYEE,
    ) as res:
        assert res.status_code == 200
        lines = [line async for line in res.aiter_lines()]
    return _parse(lines)


def _of(events: list[dict[str, Any]], kind: EventType) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == kind.value]


async def _pending(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    res = await client.get("/api/approvals?status=pending", headers=headers)
    assert res.status_code == 200
    items = res.json()["items"]
    assert items
    return items[0]


async def _run_events(client: AsyncClient, run_id: str) -> list[dict[str, Any]]:
    res = await client.get(f"/api/runs/{run_id}/events", headers=EMPLOYEE)
    assert res.status_code == 200
    return res.json()["events"]


async def test_approve_resumes_run_and_persists_ticket(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    mem_approvals: InMemoryApprovalStore,
    mem_tickets: InMemoryTicketRepository,
) -> None:
    events = await _stream(client, "打印机坏了，帮我开一张报修工单")
    required = _of(events, EventType.APPROVAL_REQUIRED)
    assert required and events[-1]["type"] == EventType.APPROVAL_REQUIRED.value
    approval_id = required[0]["payload"]["approval_id"]
    run_id = next(e["run_id"] for e in events if e["type"] == EventType.RUN_STARTED.value)

    # 挂起态：run 等审批，工单还没写
    detail = await client.get(f"/api/runs/{run_id}", headers=EMPLOYEE)
    assert detail.json()["status"] == "awaiting_approval"
    assert mem_tickets.count() == 0

    # 审批人待办里能看到；发起人自己看也能看到
    pending = await _pending(client, APPROVER)
    assert pending["approval_id"] == approval_id
    assert pending["tool"] == "create_ticket"
    assert pending["requested_by"] == "u_102"
    assert (await _pending(client, EMPLOYEE))["approval_id"] == approval_id

    res = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved", "reason": "已核对身份"},
        headers=APPROVER,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["approval"]["status"] == "approved"
    assert body["approval"]["resolved_by"] == "u_900"
    assert body["run_status"] == "completed"

    # 工单真的落库，requester 来自服务端身份
    assert mem_tickets.count() == 1
    ticket_id = next(iter(mem_tickets._tickets))
    ticket = await mem_tickets.get(ticket_id)
    assert ticket is not None
    assert ticket["requester"] == "u_102"
    assert ticket["category"] == "hardware"

    # 恢复事件：approval.resolved → tool.result(ok) → 回答里带工单号
    recovered = await _run_events(client, run_id)
    types = [e["type"] for e in recovered]
    assert EventType.APPROVAL_RESOLVED.value in types
    assert types[-1] == EventType.RUN_COMPLETED.value
    tool_ok = [
        e
        for e in recovered
        if e["type"] == EventType.TOOL_RESULT.value and e["payload"]["status"] == "ok"
    ]
    assert tool_ok
    answer = _of(recovered, EventType.MESSAGE_COMPLETED)[-1]["payload"]["text"]
    assert ticket_id in answer
    assert "已为你创建工单" in answer

    status = await mem_store.status(run_id)
    assert status == "completed"


async def test_resolve_is_idempotent(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    mem_tickets: InMemoryTicketRepository,
) -> None:
    events = await _stream(client, "帮我开一张报修工单")
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]
    run_id = next(e["run_id"] for e in events if e["type"] == EventType.RUN_STARTED.value)

    first = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved"},
        headers=APPROVER,
    )
    second = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved"},
        headers=APPROVER,
    )
    assert first.status_code == second.status_code == 200
    assert second.json()["approval"]["status"] == "approved"
    # 重复决议不能重复执行写工具，也不能重复写 approval.resolved
    assert mem_tickets.count() == 1
    resolved = [
        event
        for event in await mem_store.events_after(run_id)
        if event.type is EventType.APPROVAL_RESOLVED
    ]
    assert len(resolved) == 1


async def test_reject_does_not_execute_write(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    mem_tickets: InMemoryTicketRepository,
) -> None:
    events = await _stream(client, "帮我开一张报修工单")
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]
    run_id = next(e["run_id"] for e in events if e["type"] == EventType.RUN_STARTED.value)

    res = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "rejected", "reason": "信息不足"},
        headers=APPROVER,
    )
    assert res.status_code == 200
    assert res.json()["approval"]["status"] == "rejected"
    assert res.json()["run_status"] == "failed"

    assert mem_tickets.count() == 0
    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.error_code == "APPROVAL_REJECTED"
    assert rec.finished_at is not None


async def test_cannot_approve_own_request(client: AsyncClient) -> None:
    events = await _stream(client, "帮我开一张报修工单", headers=SELF_APPROVER)
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]

    res = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved"},
        headers=SELF_APPROVER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_non_approver_cannot_resolve(client: AsyncClient) -> None:
    events = await _stream(client, "帮我开一张报修工单")
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]

    res = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved"},
        headers=EMPLOYEE,
    )
    assert res.status_code == 403


async def test_expired_approval_fails_run(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    mem_approvals: InMemoryApprovalStore,
) -> None:
    events = await _stream(client, "帮我开一张报修工单")
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]
    run_id = next(e["run_id"] for e in events if e["type"] == EventType.RUN_STARTED.value)

    record = await mem_approvals.get(approval_id)
    assert record is not None
    mem_approvals._records[approval_id] = replace(
        record, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )

    # 打开审批列表就会触发回收
    res = await client.get("/api/approvals?status=pending", headers=APPROVER)
    assert res.status_code == 200
    assert res.json()["items"] == []

    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.status == "failed"
    assert rec.error_code == "APPROVAL_TIMEOUT"
    updated = await mem_approvals.get(approval_id)
    assert updated is not None and updated.status == "expired"


async def test_session_scope_skips_second_approval(
    client: AsyncClient,
    mem_tickets: InMemoryTicketRepository,
) -> None:
    session = "sess_grant"
    events = await _stream(client, "帮我开一张报修工单", session_id=session)
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]

    res = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved", "scope": "session"},
        headers=APPROVER,
    )
    assert res.status_code == 200
    assert mem_tickets.count() == 1

    second = await _stream(client, "帮我开一张报修工单", session_id=session)
    assert not _of(second, EventType.APPROVAL_REQUIRED)
    assert second[-1]["type"] == EventType.RUN_COMPLETED.value
    assert mem_tickets.count() == 2


async def test_approval_list_visibility(client: AsyncClient) -> None:
    await _stream(client, "帮我开一张报修工单")
    employee = await client.get("/api/approvals?status=pending", headers=EMPLOYEE)
    approver = await client.get("/api/approvals?status=pending", headers=APPROVER)
    assert len(employee.json()["items"]) == 1
    assert len(approver.json()["items"]) == 1

    other = auth_headers("u_555", ("employee",))
    other_res = await client.get("/api/approvals?status=pending", headers=other)
    assert other_res.json()["items"] == []


async def test_approval_list_paginates_with_cursor(
    client: AsyncClient, mem_approvals: InMemoryApprovalStore
) -> None:
    base = datetime.now(UTC) + timedelta(hours=1)
    ids = ["a1", "a2", "a3"]
    for index, approval_id in enumerate(ids):
        await mem_approvals.create(
            ApprovalRecord(
                id=approval_id,
                run_id=f"run_{index}",
                call_id=f"call_{index}",
                tool_name="create_ticket",
                args={"title": f"t{index}"},
                risk_level="medium",
                status="pending",
                requested_by="u_102",
                expires_at=base + timedelta(minutes=index),
                created_at=base + timedelta(seconds=index),
                state={},
            )
        )

    first = await client.get("/api/approvals?status=pending&limit=2", headers=APPROVER)
    assert first.status_code == 200
    first_body = first.json()
    assert [item["approval_id"] for item in first_body["items"]] == ids[:2]
    cursor = first_body["next_cursor"]
    assert isinstance(cursor, str) and cursor

    second = await client.get(
        f"/api/approvals?status=pending&limit=2&cursor={cursor}", headers=APPROVER
    )
    assert second.status_code == 200
    assert [item["approval_id"] for item in second.json()["items"]] == ids[2:]
    assert second.json()["next_cursor"] is None

    third = await client.get(
        f"/api/approvals?status=pending&limit=1&cursor={cursor}", headers=APPROVER
    )
    assert third.status_code == 200
    assert [item["approval_id"] for item in third.json()["items"]] == ["a3"]
    third_cursor = third.json()["next_cursor"]
    assert isinstance(third_cursor, str) and third_cursor

    empty = await client.get(
        f"/api/approvals?status=pending&limit=1&cursor={third_cursor}", headers=APPROVER
    )
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "next_cursor": None}

    bad = await client.get("/api/approvals?status=pending&cursor=not-a-cursor", headers=APPROVER)
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_CURSOR"

    missing_field = (
        base64.urlsafe_b64encode(b'{"e":"2026-01-01T00:00:00+00:00"}').decode().rstrip("=")
    )
    bad_payload = await client.get(
        f"/api/approvals?status=pending&cursor={missing_field}", headers=APPROVER
    )
    assert bad_payload.status_code == 400
    assert bad_payload.json()["code"] == "INVALID_CURSOR"


async def test_approval_list_keyset_ties_break_by_id() -> None:
    """同时间戳只靠 id 兜底；内存排序必须与 Postgres 的 keyset 全序一致。"""
    store = InMemoryApprovalStore()
    base = datetime.now(UTC) + timedelta(hours=1)
    for approval_id in ("b3", "b1", "b2"):
        await store.create(
            ApprovalRecord(
                id=approval_id,
                run_id=f"run_{approval_id}",
                call_id=f"call_{approval_id}",
                tool_name="create_ticket",
                args={"title": approval_id},
                risk_level="medium",
                status="pending",
                requested_by="u_102",
                expires_at=base,
                created_at=base,
                state={},
            )
        )

    first = await store.list(status="pending", limit=2)
    assert [record.id for record in first] == ["b1", "b2"]
    last = first[-1]
    second = await store.list(
        status="pending",
        limit=2,
        cursor=PendingApprovalCursor(last.expires_at, last.created_at, last.id),
    )
    assert [record.id for record in second] == ["b3"]


async def test_resolved_list_orders_by_resolved_at_and_ties_break_by_id() -> None:
    """已办按 `(resolved_at, id)` 倒序；同时间戳只靠 id 兜底（ADR-0053）。"""
    store = InMemoryApprovalStore()
    base = datetime.now(UTC) + timedelta(hours=1)
    for approval_id, minutes in (("d1", 0), ("d3", 2), ("d2", 2)):
        await store.create(
            ApprovalRecord(
                id=approval_id,
                run_id=f"run_{approval_id}",
                call_id=f"call_{approval_id}",
                tool_name="create_ticket",
                args={"title": approval_id},
                risk_level="medium",
                status="approved",
                requested_by="u_102",
                resolved_by="u_900",
                expires_at=base,
                created_at=base - timedelta(minutes=10),
                resolved_at=base + timedelta(minutes=minutes),
                state={},
            )
        )

    first = await store.list(status="approved", limit=2)
    assert [record.id for record in first] == ["d3", "d2"]
    last = first[-1]
    assert last.resolved_at is not None
    second = await store.list(
        status="approved",
        limit=2,
        cursor=ResolvedApprovalCursor(last.resolved_at, last.id),
    )
    assert [record.id for record in second] == ["d1"]


async def test_approval_list_resolved_paginates_with_cursor(
    client: AsyncClient, mem_approvals: InMemoryApprovalStore
) -> None:
    base = datetime.now(UTC) + timedelta(hours=1)
    ids = ["d1", "d2", "d3"]
    for index, approval_id in enumerate(ids):
        await mem_approvals.create(
            ApprovalRecord(
                id=approval_id,
                run_id=f"run_{index}",
                call_id=f"call_{index}",
                tool_name="create_ticket",
                args={"title": f"t{index}"},
                risk_level="medium",
                status="approved",
                requested_by="u_102",
                resolved_by="u_900",
                expires_at=base,
                created_at=base - timedelta(minutes=10),
                resolved_at=base + timedelta(minutes=index),
                state={},
            )
        )

    first = await client.get("/api/approvals?status=approved&limit=2", headers=APPROVER)
    assert first.status_code == 200
    first_body = first.json()
    assert [item["approval_id"] for item in first_body["items"]] == ["d3", "d2"]
    cursor = first_body["next_cursor"]
    assert isinstance(cursor, str) and cursor

    second = await client.get(
        f"/api/approvals?status=approved&limit=2&cursor={cursor}", headers=APPROVER
    )
    assert second.status_code == 200
    assert [item["approval_id"] for item in second.json()["items"]] == ["d1"]
    assert second.json()["next_cursor"] is None

    # 待办与已办游标形状不同；把待办游标用到已办上必须显式拒绝，不能静默从头开始。
    pending_cursor = (
        base64.urlsafe_b64encode(
            b'{"e":"2026-01-01T00:00:00+00:00","c":"2026-01-01T00:00:00+00:00","i":"d1"}'
        )
        .decode()
        .rstrip("=")
    )
    wrong = await client.get(
        f"/api/approvals?status=approved&cursor={pending_cursor}", headers=APPROVER
    )
    assert wrong.status_code == 400
    assert wrong.json()["code"] == "INVALID_CURSOR"

    # 已办三种状态共用 `(resolved_at, id)` 排序键，但游标里带 status，
    # approved 的游标不能静默用于 rejected（ADR-0053）。
    wrong_decided = await client.get(
        f"/api/approvals?status=rejected&cursor={cursor}", headers=APPROVER
    )
    assert wrong_decided.status_code == 400
    assert wrong_decided.json()["code"] == "INVALID_CURSOR"


async def test_resolved_list_filters_by_tool_approver_and_date() -> None:
    """已办筛选：工具/审批人精确匹配，决议日期是 UTC 半开区间（ADR-0054）。"""
    store = InMemoryApprovalStore()
    base = datetime(2026, 11, 1, 12, tzinfo=UTC)
    rows = [
        ("f1", "create_ticket", "u_900", base),
        ("f2", "query_cmdb", "u_901", base + timedelta(days=1)),
        ("f3", "create_ticket", "u_900", base + timedelta(days=2)),
    ]
    for approval_id, tool_name, resolver, resolved_at in rows:
        await store.create(
            ApprovalRecord(
                id=approval_id,
                run_id=f"run_{approval_id}",
                call_id=f"call_{approval_id}",
                tool_name=tool_name,
                args={},
                risk_level="medium",
                status="approved",
                requested_by="u_102",
                resolved_by=resolver,
                expires_at=base,
                created_at=base - timedelta(minutes=10),
                resolved_at=resolved_at,
                state={},
            )
        )

    combined = await store.list(
        status="approved",
        filters=ApprovalListFilters(
            tool_name="create_ticket",
            resolved_by="u_900",
            resolved_from=base,
            resolved_to=base + timedelta(days=2),
        ),
    )
    assert [record.id for record in combined] == ["f1"]

    open_ended = await store.list(
        status="approved",
        filters=ApprovalListFilters(resolved_from=base + timedelta(days=1)),
    )
    assert [record.id for record in open_ended] == ["f3", "f2"]

    by_tool = await store.list(
        status="approved", filters=ApprovalListFilters(tool_name="query_cmdb")
    )
    assert [record.id for record in by_tool] == ["f2"]


async def test_approval_list_filters_and_cursor_binding(
    client: AsyncClient, mem_approvals: InMemoryApprovalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API 筛选参数、日期区间与游标绑定；筛选项不能带到待办列表（ADR-0054）。"""
    base = datetime(2026, 11, 1, 12, tzinfo=UTC)
    for index, (approval_id, tool_name, resolver, resolved_at) in enumerate(
        [
            ("f1", "create_ticket", "u_900", base),
            ("f2", "create_ticket", "u_901", base + timedelta(hours=1)),
            ("f3", "query_cmdb", "u_900", base + timedelta(days=1)),
        ]
    ):
        await mem_approvals.create(
            ApprovalRecord(
                id=approval_id,
                run_id=f"run_{index}",
                call_id=f"call_{index}",
                tool_name=tool_name,
                args={},
                risk_level="medium",
                status="approved",
                requested_by="u_102",
                resolved_by=resolver,
                expires_at=base,
                created_at=base - timedelta(minutes=10),
                resolved_at=resolved_at,
                state={},
            )
        )
    # 筛选叠加在 requested_by 可见范围之上；普通员工不能借工具名看到别人的审批。
    await mem_approvals.create(
        ApprovalRecord(
            id="f4",
            run_id="run_f4",
            call_id="call_f4",
            tool_name="secret_tool",
            args={},
            risk_level="medium",
            status="approved",
            requested_by="u_555",
            resolved_by="u_900",
            expires_at=base,
            created_at=base - timedelta(minutes=10),
            resolved_at=base,
            state={},
        )
    )

    filtered = await client.get(
        "/api/approvals?status=approved&tool=create_ticket&resolved_by=u_900"
        "&resolved_from=2026-11-01&resolved_to=2026-11-01",
        headers=APPROVER,
    )
    assert filtered.status_code == 200
    assert [item["approval_id"] for item in filtered.json()["items"]] == ["f1"]

    first = await client.get(
        "/api/approvals?status=approved&tool=create_ticket&limit=1", headers=APPROVER
    )
    assert first.status_code == 200
    assert [item["approval_id"] for item in first.json()["items"]] == ["f2"]
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor

    # 用同一组筛选条件继续翻页，游标仍有效。
    second = await client.get(
        f"/api/approvals?status=approved&tool=create_ticket&limit=1&cursor={cursor}",
        headers=APPROVER,
    )
    assert second.status_code == 200
    assert [item["approval_id"] for item in second.json()["items"]] == ["f1"]

    # 筛选条件变了却复用旧游标，必须显式重来，不能静默从错误位置继续。
    mismatch = await client.get(
        f"/api/approvals?status=approved&tool=query_cmdb&cursor={cursor}",
        headers=APPROVER,
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "INVALID_CURSOR"

    pending_filter = await client.get("/api/approvals?status=pending&tool=x", headers=APPROVER)
    assert pending_filter.status_code == 422
    assert pending_filter.json()["code"] == "INVALID_FILTER"

    bad_range = await client.get(
        "/api/approvals?status=approved&resolved_from=2026-11-02&resolved_to=2026-11-01",
        headers=APPROVER,
    )
    assert bad_range.status_code == 422
    assert bad_range.json()["code"] == "INVALID_RANGE"

    blank_tool = await client.get("/api/approvals?status=approved&tool=%20", headers=APPROVER)
    assert blank_tool.status_code == 422
    assert blank_tool.json()["code"] == "INVALID_FILTER"

    max_end = await client.get(
        "/api/approvals?status=approved&resolved_to=9999-12-31", headers=APPROVER
    )
    assert max_end.status_code == 422
    assert max_end.json()["code"] == "INVALID_RANGE"

    # tool 与 approvals.tool_name 列宽一致；超长值在参数层就被拒绝。
    too_long_tool = await client.get(
        f"/api/approvals?status=approved&tool={'x' * 65}", headers=APPROVER
    )
    assert too_long_tool.status_code == 422

    approver_secret = await client.get(
        "/api/approvals?status=approved&tool=secret_tool", headers=APPROVER
    )
    assert [item["approval_id"] for item in approver_secret.json()["items"]] == ["f4"]
    employee_secret = await client.get(
        "/api/approvals?status=approved&tool=secret_tool", headers=EMPLOYEE
    )
    assert employee_secret.status_code == 200
    assert employee_secret.json()["items"] == []

    # Postgres 存储把非 UUID 的游标翻译成领域异常，API 必须回 400 而不是 503。
    async def fail_on_cursor(*, cursor: object = None, **kwargs: object) -> list[object]:
        if cursor is not None:
            raise ApprovalInvalidCursor("cursor approval id is not a UUID")
        return await original_list(**kwargs)

    original_list = mem_approvals.list
    monkeypatch.setattr(mem_approvals, "list", fail_on_cursor)
    bad_uuid = await client.get(
        f"/api/approvals?status=approved&tool=create_ticket&cursor={cursor}",
        headers=APPROVER,
    )
    assert bad_uuid.status_code == 400
    assert bad_uuid.json()["code"] == "INVALID_CURSOR"


async def test_resolve_before_approval_required_is_rejected(
    mem_store: InMemoryRunStore, mem_approvals: InMemoryApprovalStore
) -> None:
    """竞态：approval.required 还没落库时，run 仍是 running，不能先批。"""
    run_id = "6a1f2f5e-0d1c-4f40-9d4e-0f3a2b6c7d8e"
    await mem_store.create(
        run_id=run_id, user_id="u_102", session_id="s", message="帮我开一张报修工单"
    )
    service = ApprovalService(mem_store, mem_approvals)
    info = await service.request(
        run_id=run_id,
        call_id="call_1",
        session_id="s",
        tool_name="create_ticket",
        args={"title": "x", "category": "other", "priority": "P2"},
        risk_level="medium",
        state={"run_id": run_id, "user": {"id": "u_102", "roles": ["employee"]}},
        requested_by="u_102",
    )

    with pytest.raises(ApprovalNotReady):
        await service.resolve(
            info.approval_id,
            Identity(user_id="u_900", roles=frozenset({"approver"})),
            decision="approved",
        )


async def test_session_grant_does_not_leak_across_users(
    client: AsyncClient,
    mem_tickets: InMemoryTicketRepository,
) -> None:
    session = "sess_shared"
    events = await _stream(client, "帮我开一张报修工单", session_id=session)
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]
    approved = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved", "scope": "session"},
        headers=APPROVER,
    )
    assert approved.status_code == 200
    assert mem_tickets.count() == 1

    # 另一个员工复用同一个 session_id：授权是按 (user_id, session, tool) 的，不能继承
    other = auth_headers("u_555", ("employee",))
    second = await _stream(client, "帮我开一张报修工单", session_id=session, headers=other)
    assert _of(second, EventType.APPROVAL_REQUIRED)
    assert mem_tickets.count() == 1


async def test_list_maps_db_error_to_503(
    client: AsyncClient,
    mem_approvals: InMemoryApprovalStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(**_: object) -> list[object]:
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(mem_approvals, "list", boom)
    res = await client.get("/api/approvals", headers=APPROVER)
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"


async def test_resolve_maps_db_error_to_503(
    client: AsyncClient,
    mem_approvals: InMemoryApprovalStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _stream(client, "帮我开一张报修工单")
    approval_id = _of(events, EventType.APPROVAL_REQUIRED)[0]["payload"]["approval_id"]

    async def boom(_: str) -> None:
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(mem_approvals, "get", boom)
    res = await client.post(
        f"/api/approvals/{approval_id}/resolve",
        json={"decision": "approved"},
        headers=APPROVER,
    )
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"
