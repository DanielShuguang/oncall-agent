"""对话流：落库、状态投影、幂等回放与错误语义。"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore, get_store
from app.main import app
from app.schemas.event import EventType, RunStatus


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

    # id 帧与 data.seq 一致
    ids = [int(line[4:]) for line in lines if line.startswith("id: ")]
    assert ids == seqs

    run_id = str(events[0]["run_id"])
    rec = await mem_store.get(run_id)
    assert rec is not None
    assert rec.status == RunStatus.COMPLETED.value
    assert rec.event_count == len(events)
    assert rec.output is not None and "Print Spooler" in rec.output

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
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            res = await http.post(
                "/api/chat/stream",
                json={"session_id": "s", "message": "hi"},
            )
        assert res.status_code == 503
        assert res.json()["detail"] == "database unavailable"
    finally:
        app.dependency_overrides.pop(get_store, None)


async def test_invalid_request_does_not_create_run(client: AsyncClient) -> None:
    res = await client.post("/api/chat/stream", json={"session_id": "s", "message": ""})
    assert res.status_code == 422
    res = await client.post("/api/chat/stream", json={"message": "hi"})
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
