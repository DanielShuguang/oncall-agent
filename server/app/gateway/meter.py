"""模型调用计量存储（W4 D18）。

两件事必须一起做：
1. 追加一行 `model_calls`（审计 + 成本看板数据源）
2. 在同一事务里把 token/cost 增量写回 `runs`

第 2 步是 `runs.token_in == sum(model_calls.token_in)` 的保证：失败或中断的
run 不会走到 `run.completed`，如果只在那时结算，就会少统计。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from sqlalchemy import func, select

from app.models.model_call import ModelCall
from app.models.run import Run

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings

GroupBy = Literal["day", "model", "user"]
GROUP_BY_VALUES: tuple[GroupBy, ...] = ("day", "model", "user")


@dataclass(slots=True)
class ModelCallRecord:
    run_id: str
    step: str
    provider: str
    model: str
    token_in: int
    token_out: int
    cost_cents: int
    latency_ms: int
    first_token_ms: int | None
    status: str
    error: str | None
    user_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class CostItem:
    key: str
    calls: int = 0
    token_in: int = 0
    token_out: int = 0
    cost_cents: int = 0


@dataclass(slots=True)
class CostSummary:
    total_cents: int = 0
    calls: int = 0
    items: list[CostItem] = field(default_factory=list)


class ModelCallStore(Protocol):
    async def record(self, record: ModelCallRecord) -> None: ...

    async def list_for_run(self, run_id: str, limit: int = 100) -> list[ModelCallRecord]: ...

    async def totals_for_run(self, run_id: str) -> tuple[int, int, int]: ...

    async def summary(
        self,
        *,
        start: datetime,
        end: datetime,
        group_by: GroupBy,
    ) -> CostSummary: ...


class InMemoryModelCallStore:
    """测试与 `ONCALL_STORE_BACKEND=memory` 用；不落库，重启即丢。"""

    def __init__(self) -> None:
        self._records: list[ModelCallRecord] = []

    @property
    def records(self) -> list[ModelCallRecord]:
        return list(self._records)

    async def record(self, record: ModelCallRecord) -> None:
        self._records.append(record)

    async def list_for_run(self, run_id: str, limit: int = 100) -> list[ModelCallRecord]:
        return [r for r in self._records if r.run_id == run_id][:limit]

    async def totals_for_run(self, run_id: str) -> tuple[int, int, int]:
        rows = [r for r in self._records if r.run_id == run_id]
        return (
            sum(r.token_in for r in rows),
            sum(r.token_out for r in rows),
            sum(r.cost_cents for r in rows),
        )

    async def summary(
        self,
        *,
        start: datetime,
        end: datetime,
        group_by: GroupBy,
    ) -> CostSummary:
        buckets: dict[str, CostItem] = {}
        for record in self._records:
            if not start <= record.created_at < end:
                continue
            if group_by == "day":
                key = record.created_at.date().isoformat()
            elif group_by == "user":
                key = record.user_id or "unknown"
            else:
                key = record.model
            item = buckets.setdefault(key, CostItem(key=key))
            item.calls += 1
            item.token_in += record.token_in
            item.token_out += record.token_out
            item.cost_cents += record.cost_cents
        return _summary_from_items(list(buckets.values()), group_by=group_by)


class PostgresModelCallStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, record: ModelCallRecord) -> None:
        rid = uuid.UUID(record.run_id)
        async with self._sessionmaker() as session, session.begin():
            session.add(
                ModelCall(
                    run_id=rid,
                    step=record.step,
                    provider=record.provider,
                    model=record.model,
                    token_in=record.token_in,
                    token_out=record.token_out,
                    cost_cents=record.cost_cents,
                    latency_ms=record.latency_ms,
                    first_token_ms=record.first_token_ms,
                    status=record.status,
                    error=record.error,
                    created_at=record.created_at,
                )
            )
            # 与计量行同事务：失败/中断的 run 也能对上账（docs/02 §3）
            row = await session.get(Run, rid, with_for_update=True)
            if row is None:
                # run 已被删除 / 不存在：让网关感知，不能留下无主 token
                raise LookupError(f"run not found: {record.run_id}")
            row.token_in += record.token_in
            row.token_out += record.token_out
            row.cost_cents += record.cost_cents

    async def list_for_run(self, run_id: str, limit: int = 100) -> list[ModelCallRecord]:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return []
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(ModelCall)
                    .where(ModelCall.run_id == rid)
                    .order_by(ModelCall.id)
                    .limit(limit)
                )
            ).all()
        return [_record_from_row(row) for row in rows]

    async def totals_for_run(self, run_id: str) -> tuple[int, int, int]:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return (0, 0, 0)
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(ModelCall.token_in), 0),
                        func.coalesce(func.sum(ModelCall.token_out), 0),
                        func.coalesce(func.sum(ModelCall.cost_cents), 0),
                    ).where(ModelCall.run_id == rid)
                )
            ).one()
        return (int(row[0]), int(row[1]), int(row[2]))

    async def summary(
        self,
        *,
        start: datetime,
        end: datetime,
        group_by: GroupBy,
    ) -> CostSummary:
        async with self._sessionmaker() as session:
            key_column: Any
            if group_by == "user":
                key_column = Run.user_id
                stmt = (
                    select(
                        key_column.label("key"),
                        func.count(ModelCall.id),
                        func.coalesce(func.sum(ModelCall.token_in), 0),
                        func.coalesce(func.sum(ModelCall.token_out), 0),
                        func.coalesce(func.sum(ModelCall.cost_cents), 0),
                    )
                    .join(Run, Run.id == ModelCall.run_id)
                    .where(ModelCall.created_at >= start, ModelCall.created_at < end)
                    .group_by(key_column)
                )
            else:
                key_column = (
                    func.date_trunc("day", ModelCall.created_at)
                    if group_by == "day"
                    else ModelCall.model
                )
                stmt = (
                    select(
                        key_column.label("key"),
                        func.count(ModelCall.id),
                        func.coalesce(func.sum(ModelCall.token_in), 0),
                        func.coalesce(func.sum(ModelCall.token_out), 0),
                        func.coalesce(func.sum(ModelCall.cost_cents), 0),
                    )
                    .where(ModelCall.created_at >= start, ModelCall.created_at < end)
                    .group_by(key_column)
                )
            rows = (await session.execute(stmt)).all()

        items: list[CostItem] = []
        for key, calls, token_in, token_out, cost_cents in rows:
            items.append(
                CostItem(
                    key=_key_text(key, group_by),
                    calls=int(calls),
                    token_in=int(token_in),
                    token_out=int(token_out),
                    cost_cents=int(cost_cents),
                )
            )
        return _summary_from_items(items, group_by=group_by)


def _summary_from_items(items: list[CostItem], *, group_by: GroupBy) -> CostSummary:
    if group_by == "day":
        # 趋势图按时间正序，其他维度按花费倒序
        items.sort(key=lambda item: item.key)
    else:
        items.sort(key=lambda item: (item.cost_cents, item.calls, item.key), reverse=True)
    return CostSummary(
        total_cents=sum(item.cost_cents for item in items),
        calls=sum(item.calls for item in items),
        items=items,
    )


def _key_text(value: Any, group_by: GroupBy) -> str:
    if group_by == "day" and isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _record_from_row(row: ModelCall) -> ModelCallRecord:
    return ModelCallRecord(
        run_id=str(row.run_id),
        step=row.step,
        provider=row.provider,
        model=row.model,
        token_in=row.token_in,
        token_out=row.token_out,
        cost_cents=row.cost_cents,
        latency_ms=row.latency_ms,
        first_token_ms=row.first_token_ms,
        status=row.status,
        error=row.error,
        created_at=row.created_at,
    )


_model_calls: ModelCallStore | None = None


def build_model_call_store(settings: Settings) -> ModelCallStore:
    if settings.store_backend == "memory":
        return InMemoryModelCallStore()
    from app.core.db import get_sessionmaker

    return PostgresModelCallStore(get_sessionmaker())


def get_model_call_store() -> ModelCallStore:
    global _model_calls
    if _model_calls is None:
        from app.core.config import get_settings

        _model_calls = build_model_call_store(get_settings())
    return _model_calls


def set_model_call_store(value: ModelCallStore | None) -> None:
    """测试钩子。"""
    global _model_calls
    _model_calls = value


__all__ = [
    "GROUP_BY_VALUES",
    "CostItem",
    "CostSummary",
    "GroupBy",
    "InMemoryModelCallStore",
    "ModelCallRecord",
    "ModelCallStore",
    "PostgresModelCallStore",
    "build_model_call_store",
    "get_model_call_store",
    "set_model_call_store",
]
