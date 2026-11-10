"""按用户日预算覆盖的存储（ADR-0026）。

与 `tools/policy.py` 同构：定义在代码、覆盖在库里，读不到就退回默认值。
只存「与默认不同」的用户——没有行就继承 `ONCALL_USER_DAILY_BUDGET_CNY`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_sessionmaker
from app.models.base import utcnow
from app.models.user_budget import UserBudget


@dataclass(frozen=True, slots=True)
class UserBudgetOverride:
    """一条覆盖：`daily_cents = 0` 是显式的「该用户不限」。"""

    user_id: str
    daily_cents: int
    updated_by: str
    updated_at: datetime | None = None


class UserBudgetStore(Protocol):
    async def load(self) -> dict[str, UserBudgetOverride]: ...

    async def upsert(self, user_id: str, daily_cents: int, *, updated_by: str) -> None: ...

    async def delete(self, user_id: str) -> None: ...


class InMemoryUserBudgetStore:
    """测试与无库演示；进程重启即丢失，和内存 RunStore 的定位一致。"""

    def __init__(self) -> None:
        self._items: dict[str, UserBudgetOverride] = {}

    async def load(self) -> dict[str, UserBudgetOverride]:
        return dict(self._items)

    async def upsert(self, user_id: str, daily_cents: int, *, updated_by: str) -> None:
        # 内存实现也要写时间：管理页的 PUT 会回读这一行，缺时间会显示成 "-"
        self._items[user_id] = UserBudgetOverride(
            user_id=user_id,
            daily_cents=daily_cents,
            updated_by=updated_by,
            updated_at=datetime.now(UTC),
        )

    async def delete(self, user_id: str) -> None:
        self._items.pop(user_id, None)


class PostgresUserBudgetStore:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()

    async def load(self) -> dict[str, UserBudgetOverride]:
        async with self._sessionmaker() as session:
            rows = (await session.scalars(select(UserBudget))).all()
        return {
            row.user_id: UserBudgetOverride(
                user_id=row.user_id,
                daily_cents=row.daily_cents,
                updated_by=row.updated_by,
                updated_at=row.updated_at,
            )
            for row in rows
        }

    async def upsert(self, user_id: str, daily_cents: int, *, updated_by: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            stmt = pg_insert(UserBudget).values(
                user_id=user_id,
                daily_cents=daily_cents,
                updated_by=updated_by,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "daily_cents": stmt.excluded.daily_cents,
                    "updated_by": stmt.excluded.updated_by,
                    "updated_at": utcnow(),
                },
            )
            await session.execute(stmt)

    async def delete(self, user_id: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(delete(UserBudget).where(UserBudget.user_id == user_id))
