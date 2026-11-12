"""历史引用快照回填（ADR-0042）。"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.store import InMemoryRunStore, PostgresRunStore
from app.models import Base
from app.models.run import Run
from app.runs.citation_backfill import backfill_citations
from app.schemas.event import EventType

CITATION = {
    "chunk_id": 3,
    "document_id": "doc_print",
    "ord": 0,
    "title": "打印机离线排查",
    "heading": "先看队列",
    "snippet": "先检查打印队列。",
    "page": 2,
}


async def _legacy_run(
    store: InMemoryRunStore,
    *,
    message: str = "打印机坏了",
    answer: str = "先检查打印队列。",
    citations: list[dict] | None = None,
) -> str:
    """造一个 ADR-0031 之前的 run：事件有引用，但 runs.citations 为空。"""
    run_id = str(uuid.uuid4())
    await store.create(run_id=run_id, user_id="u_102", session_id="sess_backfill", message=message)
    await store.append(
        run_id,
        EventType.MESSAGE_COMPLETED,
        {"text": answer, "citations": citations if citations is not None else [CITATION]},
    )
    # 模拟迁移前的数据：事件里有引用，投影列还没写
    store._runs[run_id].citations.clear()
    return run_id


async def test_backfill_restores_snapshot_from_last_message_completed(
    mem_store: InMemoryRunStore,
) -> None:
    run_id = await _legacy_run(mem_store)
    # 第二个 candidate 的事件没有 citations，应计入 skipped
    empty_id = await _legacy_run(mem_store, message="VPN 掉了", citations=[])
    # 已经有快照的 run 不是候选
    done_id = await _legacy_run(mem_store, message="已经回填过")
    mem_store._runs[done_id].citations.append({"document_id": "doc_done"})

    result = await backfill_citations(mem_store, limit=10)

    assert result.scanned == 2
    assert result.filled == 1
    assert result.skipped_no_citations == 1
    assert result.dry_run is False
    assert mem_store._runs[run_id].citations == [CITATION]
    assert mem_store._runs[empty_id].citations == []
    assert mem_store._runs[done_id].citations == [{"document_id": "doc_done"}]


async def test_backfill_uses_the_last_message_completed_event(
    mem_store: InMemoryRunStore,
) -> None:
    run_id = await _legacy_run(mem_store)
    later = {**CITATION, "chunk_id": 9, "title": "后一次回答的引用"}
    await mem_store.append(
        run_id,
        EventType.MESSAGE_COMPLETED,
        {"text": "第二次回答", "citations": [later]},
    )
    mem_store._runs[run_id].citations.clear()

    result = await backfill_citations(mem_store)

    assert result.filled == 1
    assert mem_store._runs[run_id].citations == [later]


async def test_backfill_dry_run_is_idempotent_and_repeatable(mem_store: InMemoryRunStore) -> None:
    run_id = await _legacy_run(mem_store)

    first = await backfill_citations(mem_store, dry_run=True)
    assert first.filled == 1
    assert mem_store._runs[run_id].citations == []

    second = await backfill_citations(mem_store, dry_run=True)
    assert second.filled == 1
    assert mem_store._runs[run_id].citations == []

    written = await backfill_citations(mem_store)
    assert written.filled == 1
    assert mem_store._runs[run_id].citations == [CITATION]

    again = await backfill_citations(mem_store)
    assert again.scanned == 0
    assert again.filled == 0


async def test_backfill_skips_runs_with_pruned_content_or_events(
    mem_store: InMemoryRunStore,
) -> None:
    content_id = await _legacy_run(mem_store)
    events_id = await _legacy_run(mem_store)
    now = datetime.now(UTC)
    mem_store._runs[content_id].content_pruned_at = now
    mem_store._runs[events_id].events_pruned_at = now

    result = await backfill_citations(mem_store)

    assert result.scanned == 0
    assert mem_store._runs[content_id].citations == []
    assert mem_store._runs[events_id].citations == []


@pytest_asyncio.fixture
async def pg_store() -> AsyncIterator[PostgresRunStore]:
    url = os.environ.get("ONCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 ONCALL_TEST_DATABASE_URL 指向一个可清空的测试库")
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield PostgresRunStore(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_pg_backfill_writes_snapshot_only_when_empty(pg_store: PostgresRunStore) -> None:
    run_id = str(uuid.uuid4())
    await pg_store.create(
        run_id=run_id, user_id="u_102", session_id="sess_pg_backfill", message="打印机坏了"
    )
    await pg_store.append(
        run_id,
        EventType.MESSAGE_COMPLETED,
        {"text": "先检查打印队列。", "citations": [CITATION]},
    )
    # 模拟迁移前的行：直接清空投影列（append 会写 citations）
    async with pg_store._sessionmaker() as session, session.begin():
        await session.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(citations=[]))

    dry = await backfill_citations(pg_store, dry_run=True)
    assert dry.scanned == 1
    assert dry.filled == 1

    result = await backfill_citations(pg_store)
    assert result.filled == 1
    record = await pg_store.get(run_id)
    assert record is not None
    assert record.citations == [CITATION]

    again = await backfill_citations(pg_store)
    assert again.scanned == 0
