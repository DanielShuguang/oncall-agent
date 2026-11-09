"""Postgres 计量一致性（W4 D18/D19，默认跳过）。

核心断言：`runs.token_in == sum(model_calls.token_in)`，失败/中断的 run 也成立。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.store import PostgresRunStore
from app.gateway.meter import ModelCallRecord, PostgresModelCallStore
from app.models import Base
from app.schemas.event import EventType


@pytest_asyncio.fixture
async def pg_metrics() -> AsyncIterator[
    tuple[PostgresRunStore, PostgresModelCallStore, async_sessionmaker[AsyncSession]]
]:
    url = os.environ.get("ONCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 ONCALL_TEST_DATABASE_URL 指向一个可清空的测试库")

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    runs = PostgresRunStore(sessionmaker)
    meter = PostgresModelCallStore(sessionmaker)
    try:
        yield runs, meter, sessionmaker
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _new_run(runs: PostgresRunStore, *, user_id: str = "u_102") -> str:
    run_id = str(uuid.uuid4())
    await runs.create(
        run_id=run_id,
        user_id=user_id,
        session_id="sess_pg",
        message="打印机离线",
    )
    return run_id


async def _record(
    meter: PostgresModelCallStore,
    run_id: str,
    *,
    created_at: datetime,
    model: str = "gpt-test",
    token_in: int = 100,
    token_out: int = 20,
    cost_cents: int = 1,
    user_id: str = "u_102",
) -> None:
    await meter.record(
        ModelCallRecord(
            run_id=run_id,
            step="plan",
            provider="cloud",
            model=model,
            token_in=token_in,
            token_out=token_out,
            cost_cents=cost_cents,
            latency_ms=10,
            first_token_ms=None,
            status="ok",
            error=None,
            user_id=user_id,
            created_at=created_at,
        )
    )


async def test_meter_increments_runs_and_matches_sum(pg_metrics: tuple) -> None:
    runs, meter, _ = pg_metrics
    run_id = await _new_run(runs)
    now = datetime.now(UTC)
    await _record(meter, run_id, created_at=now, token_in=100, token_out=20, cost_cents=2)
    await _record(meter, run_id, created_at=now, token_in=50, token_out=10, cost_cents=1)

    record = await runs.get(run_id)
    assert record is not None
    assert (record.token_in, record.token_out, record.cost_cents) == (150, 30, 3)
    assert await meter.totals_for_run(run_id) == (150, 30, 3)


async def test_failed_run_still_matches_model_calls(pg_metrics: tuple) -> None:
    runs, meter, _ = pg_metrics
    run_id = await _new_run(runs)
    await _record(meter, run_id, created_at=datetime.now(UTC), cost_cents=2)
    await runs.append(
        run_id,
        EventType.RUN_FAILED,
        {"error_code": "TOOL_ERROR", "message": "工具失败", "at_step": 4},
    )

    record = await runs.get(run_id)
    assert record is not None
    assert record.status == "failed"
    assert record.failure_category == "tool"
    assert (record.token_in, record.token_out, record.cost_cents) == (100, 20, 2)
    assert (record.token_in, record.token_out, record.cost_cents) == await meter.totals_for_run(
        run_id
    )


async def test_summary_groups_and_filters_by_date(pg_metrics: tuple) -> None:
    runs, meter, _ = pg_metrics
    run_a = await _new_run(runs, user_id="u_102")
    run_b = await _new_run(runs, user_id="u_205")
    day = datetime(2026, 11, 9, 12, tzinfo=UTC)
    await _record(meter, run_a, created_at=day, model="gpt-test", cost_cents=3)
    await _record(meter, run_b, created_at=day, model="qwen", cost_cents=0)
    await _record(
        meter,
        run_a,
        created_at=day - timedelta(days=1),
        model="gpt-test",
        cost_cents=1,
    )

    summary = await meter.summary(
        start=day.replace(hour=0, minute=0, second=0, microsecond=0),
        end=day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
        group_by="model",
    )
    assert summary.total_cents == 3
    assert summary.calls == 2
    assert {item.key for item in summary.items} == {"gpt-test", "qwen"}

    by_user = await meter.summary(
        start=day - timedelta(days=1),
        end=day + timedelta(days=1),
        group_by="user",
    )
    assert {item.key for item in by_user.items} == {"u_102", "u_205"}


async def test_run_list_pagination(pg_metrics: tuple) -> None:
    runs, _, _ = pg_metrics
    ids = [await _new_run(runs) for _ in range(3)]
    first_page = await runs.list_runs(user_id="u_102", limit=2)
    assert len(first_page) == 2
    cursor = first_page[-1]
    second_page = await runs.list_runs(
        user_id="u_102",
        limit=2,
        before_started_at=cursor.started_at,
        before_run_id=cursor.run_id,
    )
    assert len(second_page) == 1
    assert {record.run_id for record in first_page + second_page} == set(ids)
