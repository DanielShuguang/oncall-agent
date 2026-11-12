"""会话列表与按会话取历史（ADR-0030）。"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore
from app.rag.access import ROLES
from app.rag.retrieve import KnowledgeBase
from app.schemas.event import EventType


async def _run(
    store: InMemoryRunStore,
    session_id: str,
    message: str,
    *,
    user_id: str = "u_102",
) -> str:
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        message=message,
    )
    return run_id


async def test_sessions_aggregate_runs_by_session(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_a", "打印机离线")
    await _run(mem_store, "sess_a", "还是不行")
    await _run(mem_store, "sess_b", "第二个会话")

    res = await client.get("/api/sessions")
    assert res.status_code == 200
    body = res.json()
    assert body["next_cursor"] is None
    items = body["items"]
    assert items[0]["session_id"] == "sess_b"
    a = next(item for item in items if item["session_id"] == "sess_a")
    assert a["title"] == "打印机离线"
    assert a["run_count"] == 2
    assert a["started_at"] is not None
    assert a["updated_at"] is not None


async def test_sessions_only_own_and_respects_limit(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_mine", "我的问题")
    await _run(mem_store, "sess_other", "别人的问题", user_id="u_205")

    res = await client.get("/api/sessions", params={"limit": 10})
    assert res.status_code == 200
    assert {item["session_id"] for item in res.json()["items"]} == {"sess_mine"}

    limited = await client.get("/api/sessions", params={"limit": 1})
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1


async def test_sessions_title_falls_back_and_truncates(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_blank", "   ")
    await _run(mem_store, "sess_blank", "真实问题")
    await _run(mem_store, "sess_none", "   ")
    await _run(mem_store, "sess_long", "打" * 100)
    await _run(mem_store, "sess_exact", "字" * 60)

    response = await client.get("/api/sessions")
    items = {item["session_id"]: item for item in response.json()["items"]}
    assert items["sess_blank"]["title"] == "真实问题"
    assert items["sess_none"]["title"] is None
    assert items["sess_long"]["title"] is not None
    assert len(items["sess_long"]["title"]) == 60
    assert items["sess_long"]["title"].endswith("…")
    assert items["sess_exact"]["title"] == "字" * 60


async def test_runs_can_be_filtered_by_session(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    a_run = await _run(mem_store, "sess_a", "会话 A")
    await _run(mem_store, "sess_b", "会话 B")

    res = await client.get("/api/runs", params={"session_id": "sess_a"})
    assert res.status_code == 200
    assert [item["run_id"] for item in res.json()["items"]] == [a_run]

    missing = await client.get("/api/runs", params={"session_id": "sess_missing"})
    assert missing.status_code == 200
    assert missing.json()["items"] == []


async def test_sessions_paginate_with_cursor(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_a", "会话 A")
    await asyncio.sleep(0.005)
    await _run(mem_store, "sess_b", "会话 B")
    await asyncio.sleep(0.005)
    await _run(mem_store, "sess_c", "会话 C")

    first = await client.get("/api/sessions", params={"limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert [item["session_id"] for item in first_body["items"]] == ["sess_c", "sess_b"]
    assert first_body["next_cursor"] is not None

    second = await client.get(
        "/api/sessions", params={"limit": 2, "cursor": first_body["next_cursor"]}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["session_id"] for item in second_body["items"]] == ["sess_a"]
    assert second_body["next_cursor"] is None


async def test_sessions_search_by_title_is_case_insensitive(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_print", "打印机离线")
    await asyncio.sleep(0.005)
    await _run(mem_store, "sess_vpn", "VPN 连不上")
    await asyncio.sleep(0.005)
    await _run(mem_store, "sess_jam", "打印机卡纸")

    res = await client.get("/api/sessions", params={"q": "打印机"})
    assert res.status_code == 200
    assert [item["session_id"] for item in res.json()["items"]] == ["sess_jam", "sess_print"]

    lower = await client.get("/api/sessions", params={"q": "vpn"})
    assert [item["session_id"] for item in lower.json()["items"]] == ["sess_vpn"]

    missing = await client.get("/api/sessions", params={"q": "不存在的话题"})
    assert missing.status_code == 200
    assert missing.json() == {"items": [], "next_cursor": None}

    # % / _ 是普通字符，不能当通配符
    literal = await client.get("/api/sessions", params={"q": "%"})
    assert literal.json()["items"] == []


async def test_sessions_search_paginates_and_validates_query(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    for index in range(3):
        await _run(mem_store, f"sess_p{index}", f"打印机问题 {index}")
        await asyncio.sleep(0.005)

    first = await client.get("/api/sessions", params={"q": "打印机", "limit": 2})
    body = first.json()
    assert [item["session_id"] for item in body["items"]] == ["sess_p2", "sess_p1"]
    assert body["next_cursor"] is not None
    second = await client.get(
        "/api/sessions",
        params={"q": "打印机", "limit": 2, "cursor": body["next_cursor"]},
    )
    assert [item["session_id"] for item in second.json()["items"]] == ["sess_p0"]

    assert (await client.get("/api/sessions", params={"q": "x" * 101})).status_code == 422


async def test_sessions_reject_invalid_cursor(client: AsyncClient) -> None:
    res = await client.get("/api/sessions", params={"cursor": "not-a-cursor"})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURSOR"


async def test_session_history_pages_older_runs(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _run(mem_store, "sess_a", "第一轮")
    await asyncio.sleep(0.005)
    second = await _run(mem_store, "sess_a", "第二轮")
    await asyncio.sleep(0.005)
    third = await _run(mem_store, "sess_a", "第三轮")

    first = await client.get("/api/runs", params={"session_id": "sess_a", "limit": 2})
    first_body = first.json()
    assert [item["run_id"] for item in first_body["items"]] == [third, second]
    assert first_body["next_cursor"] is not None

    older = await client.get(
        "/api/runs",
        params={"session_id": "sess_a", "limit": 2, "cursor": first_body["next_cursor"]},
    )
    older_body = older.json()
    assert len(older_body["items"]) == 1
    assert older_body["items"][0]["run_id"] not in {second, third}
    assert older_body["next_cursor"] is None


async def test_sessions_reject_bad_limit(client: AsyncClient) -> None:
    assert (await client.get("/api/sessions", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/sessions", params={"limit": 51})).status_code == 422


async def test_sessions_database_failure_is_503(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    mem_store.list_sessions = AsyncMock(side_effect=SQLAlchemyError("boom"))  # type: ignore[method-assign]

    res = await client.get("/api/sessions")
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"


async def _detail(
    store: InMemoryRunStore,
    session_id: str,
    message: str,
    *,
    citations: list[dict[str, object]] | None = None,
    with_tool: bool = False,
    user_id: str = "u_102",
) -> str:
    """造一条有正文（可选引用/工具事件）的历史 run。"""
    run_id = str(uuid.uuid4())
    await store.create(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        message=message,
    )
    await store.append(run_id, EventType.RUN_STARTED, {"model": "mock", "max_steps": 12})
    payload: dict[str, object] = {"text": f"回答：{message}"}
    if citations is not None:
        payload["citations"] = citations
    await store.append(run_id, EventType.MESSAGE_COMPLETED, payload)
    if with_tool:
        await store.append(
            run_id,
            EventType.TOOL_CALL,
            {"call_id": f"call_{run_id}", "tool": "query_cmdb", "args": {}, "write": False},
        )
        await store.append(
            run_id,
            EventType.TOOL_RESULT,
            {"call_id": f"call_{run_id}", "tool": "query_cmdb", "status": "ok", "result": {}},
        )
    await store.append(run_id, EventType.RUN_COMPLETED, {"status": "completed", "steps": 1})
    return run_id


async def _public_doc(kb: KnowledgeBase) -> str:
    info, _ = await kb.index_text(
        title="打印机驱动",
        text="# 打印机驱动\n\n重启打印服务即可。\n",
        source=f"seed:{uuid.uuid4().hex}.md",
    )
    return info.id


async def test_session_runs_batch_returns_details_and_timeline(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """批量详情一次返回正文/引用/运行过程，且不带 model_calls（ADR-0036）。"""
    doc_id = await _public_doc(memory_kb)
    older = await _detail(
        mem_store,
        "sess_batch",
        "怎么装驱动",
        citations=[
            {
                "chunk_id": 0,
                "document_id": doc_id,
                "ord": 0,
                "title": "打印机驱动",
                "snippet": "重启打印服务即可。",
            }
        ],
    )
    await asyncio.sleep(0.005)
    newer = await _detail(mem_store, "sess_batch", "重启了还是不行", with_tool=True)

    res = await client.get("/api/sessions/sess_batch/runs")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "sess_batch"
    assert body["next_cursor"] is None
    assert [item["run_id"] for item in body["items"]] == [newer, older]
    first = body["items"][0]
    assert "model_calls" not in first
    assert first["content_redacted"] is False
    assert [item["kind"] for item in first["timeline"]] == ["tool"]
    assert first["timeline"][0]["status"] == "ok"
    second = body["items"][1]
    assert second["citations"][0]["document_id"] == doc_id


async def test_session_runs_missing_or_foreign_session_is_404(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _detail(mem_store, "sess_other", "别人的会话", user_id="u_205")

    assert (await client.get("/api/sessions/sess_missing/runs")).status_code == 404
    assert (await client.get("/api/sessions/sess_other/runs")).status_code == 404
    # 空 cursor 按「没有游标」处理，不能把 404 变成 200 空页
    empty_cursor = await client.get("/api/sessions/sess_missing/runs", params={"cursor": ""})
    assert empty_cursor.status_code == 404


async def test_session_runs_rejects_bad_limit(client: AsyncClient) -> None:
    assert (await client.get("/api/sessions/sess_any/runs", params={"limit": 0})).status_code == 422
    assert (
        await client.get("/api/sessions/sess_any/runs", params={"limit": 51})
    ).status_code == 422


async def test_session_runs_database_failure_is_503(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    mem_store.list_runs = AsyncMock(side_effect=SQLAlchemyError("boom"))  # type: ignore[method-assign]

    res = await client.get("/api/sessions/sess_any/runs")
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"


async def test_session_runs_paginate_older_runs(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    first = await _detail(mem_store, "sess_page", "第一轮")
    await asyncio.sleep(0.005)
    second = await _detail(mem_store, "sess_page", "第二轮")
    await asyncio.sleep(0.005)
    third = await _detail(mem_store, "sess_page", "第三轮")

    page = await client.get("/api/sessions/sess_page/runs", params={"limit": 2})
    body = page.json()
    assert [item["run_id"] for item in body["items"]] == [third, second]
    assert body["next_cursor"] is not None

    older = await client.get(
        "/api/sessions/sess_page/runs",
        params={"limit": 2, "cursor": body["next_cursor"]},
    )
    older_body = older.json()
    assert [item["run_id"] for item in older_body["items"]] == [first]
    assert older_body["next_cursor"] is None

    bad = await client.get(
        "/api/sessions/sess_page/runs",
        params={"cursor": "not-a-cursor"},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_CURSOR"


async def test_session_runs_cursor_past_end_returns_empty_page(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    await _detail(mem_store, "sess_empty", "唯一一轮")

    page = await client.get("/api/sessions/sess_empty/runs", params={"limit": 1})
    body = page.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is not None

    empty = await client.get(
        "/api/sessions/sess_empty/runs",
        params={"limit": 1, "cursor": body["next_cursor"]},
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["next_cursor"] is None


async def test_session_runs_redacts_only_the_restricted_run(
    client: AsyncClient, mem_store: InMemoryRunStore, memory_kb: KnowledgeBase
) -> None:
    """同一页里被回收的 run 只影响自己，正文与运行过程一起收起。"""
    public_id = await _public_doc(memory_kb)
    hidden_id = await _public_doc(memory_kb)
    await memory_kb.set_access(hidden_id, visibility=ROLES, allowed_roles=("hr",))

    visible = await _detail(
        mem_store,
        "sess_mix",
        "公开问题",
        citations=[{"document_id": public_id, "chunk_id": 0, "ord": 0}],
        with_tool=True,
    )
    await asyncio.sleep(0.005)
    hidden = await _detail(
        mem_store,
        "sess_mix",
        "受限问题",
        citations=[{"document_id": hidden_id, "chunk_id": 0, "ord": 0}],
        with_tool=True,
    )

    body = (await client.get("/api/sessions/sess_mix/runs")).json()
    items = {item["run_id"]: item for item in body["items"]}

    assert items[visible]["content_redacted"] is False
    assert items[visible]["output"] is not None
    assert items[visible]["timeline_available"] is True

    assert items[hidden]["content_redacted"] is True
    assert items[hidden]["output"] is None
    assert items[hidden]["citations"] == []
    assert items[hidden]["timeline"] == []
    assert items[hidden]["timeline_available"] is False
