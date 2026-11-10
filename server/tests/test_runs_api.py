"""运行查询与断线续传接口。"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.core.store import InMemoryRunStore
from app.gateway.meter import InMemoryModelCallStore, ModelCallRecord
from app.main import app
from app.rag.access import PUBLIC, ROLES
from app.rag.retrieve import KnowledgeBase
from app.schemas.event import EventType, RunStatus
from tests.support import auth_headers


async def _index_doc(
    kb: KnowledgeBase,
    *,
    visibility: str = PUBLIC,
    allowed_roles: tuple[str, ...] = (),
) -> str:
    info, _chunks = await kb.index_text(
        title="薪酬与年终奖",
        text="# 薪酬与年终奖\n\n## 年终奖\n\n年终奖在次年 1 月随工资发放。\n",
        source=f"seed:{uuid.uuid4().hex}.md",
        visibility=visibility,
        allowed_roles=allowed_roles,
    )
    return info.id


async def _seed_run(
    store: InMemoryRunStore,
    *,
    client_msg_id: str | None = None,
    user_id: str = "u_102",
    status: str = "completed",
    citations: list[dict[str, Any]] | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id=user_id,
        session_id="sess_1",
        message="打印机离线",
        client_msg_id=client_msg_id or f"cmsg_{uuid.uuid4().hex[:8]}",
    )
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock", "max_steps": 12})
    await store.append(run_id, EventType.STEP_STARTED, {"node": "intake"})
    await store.append(run_id, EventType.STEP_COMPLETED, {"node": "intake"})
    payload: dict[str, Any] = {"text": "重启打印服务"}
    if citations is not None:
        payload["citations"] = citations
    await store.append(run_id, EventType.MESSAGE_COMPLETED, payload)
    if status == "failed":
        await store.append(
            run_id,
            EventType.RUN_FAILED,
            {"error_code": "TOOL_ERROR", "message": "失败", "at_step": 4},
        )
    else:
        await store.append(
            run_id,
            EventType.RUN_COMPLETED,
            {"status": "completed", "steps": 1, "token_in": 12, "token_out": 3, "cost_cents": 1},
        )
    return run_id


async def test_get_run_detail(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(f"/api/runs/{run_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == run_id
    assert body["status"] == RunStatus.COMPLETED.value
    assert body["input"] == "打印机离线"
    assert body["output"] == "重启打印服务"
    assert body["event_count"] == 5
    assert body["token_in"] == 12
    assert body["cost_cents"] == 1
    assert body["finished_at"] is not None
    assert body["events_pruned_at"] is None


async def test_get_run_unknown_returns_404(client: AsyncClient) -> None:
    res = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert res.status_code == 404


async def test_events_after_seq(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(f"/api/runs/{run_id}/events", params={"after_seq": 2})
    assert res.status_code == 200
    body = res.json()
    assert [e["seq"] for e in body["events"]] == [3, 4, 5]
    assert body["next_seq"] == 5
    assert body["run_status"] == RunStatus.COMPLETED.value


async def test_events_last_event_id_header(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": "3"},
    )
    assert res.status_code == 200
    assert [e["seq"] for e in res.json()["events"]] == [4, 5]


async def test_explicit_after_seq_overrides_header(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(
        f"/api/runs/{run_id}/events",
        params={"after_seq": 0},
        headers={"Last-Event-ID": "3"},
    )
    assert [e["seq"] for e in res.json()["events"]] == [1, 2, 3, 4, 5]


async def test_invalid_last_event_id_falls_back_to_zero(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": "not-a-number"},
    )
    assert [e["seq"] for e in res.json()["events"]] == [1, 2, 3, 4, 5]


async def test_events_limit_and_next_seq(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    run_id = await _seed_run(mem_store)

    res = await client.get(f"/api/runs/{run_id}/events", params={"limit": 2})
    body = res.json()
    assert [e["seq"] for e in body["events"]] == [1, 2]
    assert body["next_seq"] == 2


async def test_events_unknown_run_returns_404(client: AsyncClient) -> None:
    res = await client.get(f"/api/runs/{uuid.uuid4()}/events")
    assert res.status_code == 404


async def test_run_of_another_user_is_404(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    """不能读别人的 run，也不能用 403 暴露"它存在"。"""
    run_id = await _seed_run(mem_store)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=auth_headers("u_205"),
    ) as other:
        assert (await other.get(f"/api/runs/{run_id}")).status_code == 404
        assert (await other.get(f"/api/runs/{run_id}/events")).status_code == 404


async def test_list_runs_paginates_with_cursor(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_ids = [await _seed_run(mem_store) for _ in range(3)]
    base = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    for index, run_id in enumerate(run_ids):
        record = await mem_store.get(run_id)
        assert record is not None
        record.started_at = base + timedelta(minutes=index)

    first = await client.get("/api/runs", params={"limit": 2})
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]

    second = await client.get("/api/runs", params={"limit": 2, "cursor": body["next_cursor"]})
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None
    assert second_body["items"][0]["run_id"] == run_ids[0]


async def test_list_runs_filters_status_and_owner(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    failed_id = await _seed_run(mem_store, status="failed")
    await _seed_run(mem_store)
    await _seed_run(mem_store, user_id="u_205")

    res = await client.get("/api/runs", params={"status": "failed"})
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["run_id"] for item in items] == [failed_id]
    assert items[0]["failure_category"] == "tool"
    assert items[0]["error_code"] == "TOOL_ERROR"


async def test_list_runs_rejects_invalid_cursor(client: AsyncClient) -> None:
    res = await client.get("/api/runs", params={"cursor": "not-base64"})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_list_runs_rejects_cursor_with_non_uuid_run_id(client: AsyncClient) -> None:
    cursor = base64.urlsafe_b64encode(b"2026-11-09T10:00:00+00:00|not-a-uuid").decode()
    res = await client.get("/api/runs", params={"cursor": cursor})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_list_runs_rejects_naive_cursor_datetime(client: AsyncClient) -> None:
    cursor = base64.urlsafe_b64encode(f"2026-11-09T10:00:00|{uuid.uuid4()}".encode()).decode()
    res = await client.get("/api/runs", params={"cursor": cursor})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_run_detail_includes_model_calls(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    mem_model_calls: InMemoryModelCallStore,
) -> None:
    run_id = await _seed_run(mem_store)
    await mem_model_calls.record(
        ModelCallRecord(
            run_id=run_id,
            step="plan",
            provider="local",
            model="qwen-test",
            token_in=100,
            token_out=20,
            cost_cents=0,
            latency_ms=12,
            first_token_ms=None,
            status="ok",
            error=None,
            user_id="u_102",
        )
    )

    res = await client.get(f"/api/runs/{run_id}")
    assert res.status_code == 200
    calls = res.json()["model_calls"]
    assert len(calls) == 1
    assert calls[0]["step"] == "plan"
    assert calls[0]["token_in"] == 100


async def test_pruned_events_are_marked_in_detail(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    """保留清理后 run 仍在：详情带 events_pruned_at，事件接口返回空而不是 404。"""
    run_id = await _seed_run(mem_store)
    pruned = await mem_store.prune_events(finished_before=datetime.now(UTC) + timedelta(days=365))
    assert pruned.run_ids == [run_id]

    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["events_pruned_at"] is not None
    assert detail["event_count"] == 0
    # 摘要与回答保留：回放不可用不等于 run 消失
    assert detail["output"] == "重启打印服务"
    assert detail["content_redacted"] is False
    assert detail["status"] == RunStatus.COMPLETED.value

    events = await client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    payload = events.json()
    assert payload["events"] == []
    assert payload["run_status"] == RunStatus.COMPLETED.value


async def test_cited_public_document_keeps_output(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    doc_id = await _index_doc(memory_kb)
    run_id = await _seed_run(mem_store, citations=[{"document_id": doc_id, "title": "薪酬"}])

    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["content_redacted"] is False
    assert detail["output"] == "重启打印服务"

    events = (await client.get(f"/api/runs/{run_id}/events")).json()
    assert events["content_redacted"] is False
    assert [e["seq"] for e in events["events"]] == [1, 2, 3, 4, 5]


async def test_revoked_document_redacts_output_and_events(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """引用文档被改窄（ADR-0022）：回答正文与事件不再返回，run 摘要仍在。"""
    doc_id = await _index_doc(memory_kb)
    run_id = await _seed_run(mem_store, citations=[{"document_id": doc_id}])
    await memory_kb.set_access(doc_id, visibility=ROLES, allowed_roles=("hr",))

    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["content_redacted"] is True
    assert detail["output"] is None
    # 用户自己敲进来的问题不回收
    assert detail["input"] == "打印机离线"
    assert detail["status"] == RunStatus.COMPLETED.value

    events = (await client.get(f"/api/runs/{run_id}/events")).json()
    assert events["content_redacted"] is True
    assert events["events"] == []
    assert events["next_seq"] == 0
    assert events["run_status"] == RunStatus.COMPLETED.value


async def test_restoring_visibility_restores_content(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """回收是读时判定，不改存储：可见范围改回去，旧回答立刻恢复。"""
    doc_id = await _index_doc(memory_kb)
    run_id = await _seed_run(mem_store, citations=[{"document_id": doc_id}])
    await memory_kb.set_access(doc_id, visibility=ROLES, allowed_roles=("hr",))
    assert (await client.get(f"/api/runs/{run_id}")).json()["content_redacted"] is True

    await memory_kb.set_access(doc_id, visibility=PUBLIC, allowed_roles=())
    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["content_redacted"] is False
    assert detail["output"] == "重启打印服务"


async def test_admin_role_sees_cited_content(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """admin 是知识库所有者（ADR-0019）：回收只约束非所有者。"""
    doc_id = await _index_doc(memory_kb)
    run_id = await _seed_run(mem_store, citations=[{"document_id": doc_id}])
    await memory_kb.set_access(doc_id, visibility=ROLES, allowed_roles=("hr",))

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers(roles=("admin",)))
    assert res.json()["content_redacted"] is False
    assert res.json()["output"] == "重启打印服务"


async def test_matching_role_sees_cited_content(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """按**当前**角色判定：同一用户换成 hr 角色读，引用文档就可见。"""
    doc_id = await _index_doc(memory_kb, visibility=ROLES, allowed_roles=("hr",))
    run_id = await _seed_run(mem_store, citations=[{"document_id": doc_id}])

    assert (await client.get(f"/api/runs/{run_id}")).json()["content_redacted"] is True
    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers(roles=("hr",)))
    assert res.json()["content_redacted"] is False


async def test_deleted_document_redacts_content(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    """查不到的文档按不可见处理（fail-closed）：删除也是一种收权。"""
    run_id = await _seed_run(mem_store, citations=[{"document_id": str(uuid.uuid4())}])
    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["content_redacted"] is True
    assert detail["output"] is None


async def test_events_pruned_and_redacted_together(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """事件已被保留清理、引用又不可见：两个标记同时成立时仍返回空事件 200。"""
    doc_id = await _index_doc(memory_kb)
    run_id = await _seed_run(mem_store, citations=[{"document_id": doc_id}])
    await mem_store.prune_events(finished_before=datetime.now(UTC) + timedelta(days=365))
    await memory_kb.set_access(doc_id, visibility=ROLES, allowed_roles=("hr",))

    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["events_pruned_at"] is not None
    assert detail["content_redacted"] is True
    assert detail["output"] is None

    events = (await client.get(f"/api/runs/{run_id}/events")).json()
    assert events["events"] == []
    assert events["content_redacted"] is True

    # 列表与详情共用同一个 summary，标记也要出现在列表里
    listing = (await client.get("/api/runs")).json()
    assert listing["items"][0]["events_pruned_at"] is not None
