"""对话流：落库、状态投影、幂等回放与错误语义。"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.chat import _with_heartbeat
from app.core.store import InMemoryRunStore, get_store
from app.main import app
from app.schemas.event import EventType, RunStatus
from tests.support import auth_headers


def _parse(lines: list[str]) -> list[dict[str, object]]:
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


async def _stream(
    client: AsyncClient,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
) -> list[str]:
    async with client.stream(
        "POST", "/api/chat/stream", json=payload, headers=headers or {}
    ) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        return [line async for line in res.aiter_lines()]


async def test_stream_persists_events_and_completes(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    lines = await _stream(
        client,
        {
            "session_id": "sess_1",
            "client_msg_id": "cmsg_1",
            "message": "我电脑连不上打印机了",
        },
    )
    events = _parse(lines)
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1))
    assert events[0]["type"] == EventType.RUN_STARTED.value
    assert events[-1]["type"] == EventType.RUN_COMPLETED.value
    assert any(e["type"] == EventType.MESSAGE_COMPLETED.value for e in events)
    # W1 D5：工具调用经治理层真实执行并落库（不是脚本化事件）
    assert any(e["type"] == EventType.TOOL_CALL.value for e in events)
    tool_results = [e for e in events if e["type"] == EventType.TOOL_RESULT.value]
    assert tool_results[0]["payload"]["status"] == "ok"
    completed = next(e for e in events if e["type"] == EventType.RUN_COMPLETED.value)
    assert completed["payload"]["steps"] == 7

    # id 帧与 data.seq 一致
    ids = [int(line[4:]) for line in lines if line.startswith("id: ")]
    assert ids == seqs

    run_id = str(events[0]["run_id"])
    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.COMPLETED.value
    assert rec.event_count == len(events)
    assert rec.output is not None and "打印机" in rec.output

    res = await client.get(f"/api/runs/{run_id}")
    assert res.json()["status"] == RunStatus.COMPLETED.value


async def test_stream_waits_for_approval(client: AsyncClient, mem_store: InMemoryRunStore) -> None:
    lines = await _stream(
        client,
        {"session_id": "sess_1", "message": "帮我开一张报修工单"},
    )
    events = _parse(lines)
    assert events[-1]["type"] == EventType.APPROVAL_REQUIRED.value

    run_id = str(events[0]["run_id"])
    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.AWAITING_APPROVAL.value


async def test_duplicate_client_msg_id_replays_without_rerun(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    payload = {
        "session_id": "sess_1",
        "client_msg_id": "cmsg_dup",
        "message": "我电脑连不上打印机了",
    }
    first = _parse(await _stream(client, payload))
    run_id = str(first[0]["run_id"])
    rec = await mem_store.get(run_id)
    assert rec is not None
    count_before = rec.event_count

    second = _parse(await _stream(client, payload))
    assert [e["seq"] for e in second] == [e["seq"] for e in first]
    assert second[0]["run_id"] == run_id

    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.event_count == count_before


async def test_blank_client_msg_id_is_treated_as_absent(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    first = _parse(
        await _stream(client, {"session_id": "s", "client_msg_id": "", "message": "打印机"})
    )
    second = _parse(
        await _stream(client, {"session_id": "s", "client_msg_id": "", "message": "打印机"})
    )
    assert first[0]["run_id"] != second[0]["run_id"]


async def test_duplicate_running_run_tails_to_terminal(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    run_id = str(uuid.uuid4())
    await mem_store.create(
        run_id=run_id,
        user_id="u_102",
        session_id="s",
        message="旧问题",
        client_msg_id="cmsg_tail",
    )
    await mem_store.append(run_id, EventType.RUN_STARTED, {})

    task = asyncio.create_task(
        _stream(client, {"session_id": "s", "client_msg_id": "cmsg_tail", "message": "旧问题"})
    )
    await asyncio.sleep(0.05)
    await mem_store.append(run_id, EventType.RUN_COMPLETED, {"steps": 0})

    events = _parse(await task)
    assert [e["seq"] for e in events] == [1, 2]


async def test_heartbeat_is_emitted_between_idle_events() -> None:
    async def source():
        await asyncio.sleep(0.05)
        yield "data: x\n\n"

    async def run() -> list[str]:
        return [frame async for frame in _with_heartbeat(source(), interval=0.01)]

    frames = await run()
    assert any(frame.startswith(": heartbeat") for frame in frames)
    assert frames[-1].startswith("data: ")


async def test_duplicate_with_last_event_id_resumes(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    payload = {
        "session_id": "sess_1",
        "client_msg_id": "cmsg_resume",
        "message": "我电脑连不上打印机了",
    }
    first = _parse(await _stream(client, payload))
    resumed = _parse(await _stream(client, payload, headers={"Last-Event-ID": "3"}))
    assert [e["seq"] for e in resumed] == [e["seq"] for e in first if e["seq"] > 3]


async def test_store_failure_before_stream_returns_503() -> None:
    class BrokenStore:
        async def create(self, **kwargs: object) -> tuple[object, bool]:
            raise SQLAlchemyError("db down")

    app.dependency_overrides[get_store] = lambda: BrokenStore()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=auth_headers()
        ) as http:
            res = await http.post(
                "/api/chat/stream",
                json={"session_id": "s", "message": "hi"},
            )
        assert res.status_code == 503
        assert res.json()["detail"] == "database unavailable"
    finally:
        app.dependency_overrides.pop(get_store, None)


async def test_append_failure_marks_run_failed(
    client: AsyncClient,
    mem_store: InMemoryRunStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = mem_store.append
    calls = {"n": 0}

    async def flaky(
        run_id: str, event_type: EventType, payload: dict[str, object] | None = None
    ) -> object:
        calls["n"] += 1
        if calls["n"] == 3:
            raise SQLAlchemyError("db down")
        return await original(run_id, event_type, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(mem_store, "append", flaky)

    events = _parse(await _stream(client, {"session_id": "s", "message": "打印机"}))
    assert len(events) == 2

    run_id = str(events[0]["run_id"])
    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.FAILED.value
    assert rec.error_code == "STORE_WRITE_FAILED"


async def test_invalid_request_does_not_create_run(client: AsyncClient) -> None:
    res = await client.post("/api/chat/stream", json={"session_id": "s", "message": ""})
    assert res.status_code == 422
    res = await client.post("/api/chat/stream", json={"message": "hi"})
    assert res.status_code == 422
    # model 是用户可控字符串，必须有上限，不能随便写进 runs.model / 事件 payload
    res = await client.post(
        "/api/chat/stream",
        json={"session_id": "s", "message": "hi", "options": {"model": "x" * 101}},
    )
    assert res.status_code == 422


@pytest.mark.parametrize("last_event_id", ["0", "1"])
async def test_resume_header_on_fresh_run_is_accepted(
    client: AsyncClient, last_event_id: str
) -> None:
    """新 run 带 Last-Event-ID 不应报错（浏览器重连可能带旧值）。"""
    lines = await _stream(
        client,
        {"session_id": "s", "message": "打印机"},
        headers={"Last-Event-ID": last_event_id},
    )
    assert _parse(lines)[0]["seq"] == 1
