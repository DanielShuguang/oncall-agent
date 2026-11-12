"""工具覆盖策略：数据库覆盖 + 短 TTL 缓存（W5 D22/D23）。

`ToolGuard` 每次执行前调用 `ToolPolicy.apply()`，把代码里的 `ToolSpec` 与本环境
的覆盖合并。策略读库失败时退回上一次快照（没有快照则退回代码默认值）并记日志：
管理配置的短暂不可用不应该让所有工具调用一起 500；真正的权限边界仍由代码里的
`roles` / `is_write` / 保留字段闸门兜底。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from time import monotonic
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.tool_setting import ToolSetting
from app.models.tool_setting import ToolSettingChange as ToolSettingChangeRow
from app.tools.registry import ToolSpec

log = get_logger(__name__)

#: 多进程部署时管理员改完配置最多这么久生效；单进程会 invalidate 立即生效
POLICY_TTL_S = 2.0


@dataclass(frozen=True, slots=True)
class ToolOverride:
    """NULL 语义：enabled=None 继承代码默认；roles=None 继承，roles=() 表示所有人。"""

    enabled: bool | None = None
    roles: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ToolSettingChange:
    """一次管理写入里真正发生的单工具变化（ADR-0037）。"""

    tool_name: str
    changed_by: str
    source: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ToolSettingChangeRecord:
    """审计页读出的历史行。"""

    id: int
    tool_name: str
    changed_by: str
    changed_at: datetime
    source: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


def override_snapshot(override: ToolOverride | None) -> dict[str, Any] | None:
    """把覆盖转成审计快照；None 表示没有覆盖（走代码默认）。"""
    if override is None:
        return None
    return {
        "enabled": override.enabled,
        "roles": None if override.roles is None else list(override.roles),
    }


class ToolSettingStore(Protocol):
    async def load(self) -> dict[str, ToolOverride]: ...

    async def upsert(
        self,
        name: str,
        override: ToolOverride | None,
        *,
        updated_by: str,
        change: ToolSettingChange | None = None,
    ) -> None: ...

    async def replace(
        self,
        overrides: Mapping[str, ToolOverride],
        *,
        updated_by: str,
        changes: Sequence[ToolSettingChange] = (),
    ) -> None: ...

    async def history(self, name: str, *, limit: int = 20) -> list[ToolSettingChangeRecord]: ...


class InMemoryToolSettingStore:
    """测试与无库演示；进程重启即丢失，和内存 RunStore 的定位一致。"""

    def __init__(self) -> None:
        self._items: dict[str, ToolOverride] = {}
        self._history: list[ToolSettingChangeRecord] = []
        self._next_id = 1

    async def load(self) -> dict[str, ToolOverride]:
        return dict(self._items)

    async def upsert(
        self,
        name: str,
        override: ToolOverride | None,
        *,
        updated_by: str,
        change: ToolSettingChange | None = None,
    ) -> None:
        if override is None:
            self._items.pop(name, None)
        else:
            self._items[name] = override
        if change is not None:
            self._history.append(self._new_record(change))

    async def replace(
        self,
        overrides: Mapping[str, ToolOverride],
        *,
        updated_by: str,
        changes: Sequence[ToolSettingChange] = (),
    ) -> None:
        self._items = dict(overrides)
        # 与 Postgres 同一事务的 now() 对齐：一次提交的记录共享时间戳，
        # 否则按时间倒序读出来会变成「后写的工具排在前面」的伪顺序。
        changed_at = utcnow() if changes else None
        for change in changes:
            self._history.append(self._new_record(change, changed_at=changed_at))

    async def history(self, name: str, *, limit: int = 20) -> list[ToolSettingChangeRecord]:
        rows = sorted(
            (row for row in self._history if row.tool_name == name),
            key=lambda row: (row.changed_at, row.id),
            reverse=True,
        )
        return rows[:limit]

    def _new_record(
        self, change: ToolSettingChange, *, changed_at: datetime | None = None
    ) -> ToolSettingChangeRecord:
        record = ToolSettingChangeRecord(
            id=self._next_id,
            tool_name=change.tool_name,
            changed_by=change.changed_by,
            changed_at=changed_at or utcnow(),
            source=change.source,
            before=change.before,
            after=change.after,
        )
        self._next_id += 1
        return record


class PostgresToolSettingStore:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()

    async def load(self) -> dict[str, ToolOverride]:
        async with self._sessionmaker() as session:
            rows = (await session.scalars(select(ToolSetting))).all()
        return {
            row.name: ToolOverride(
                enabled=row.enabled,
                roles=None if row.roles is None else tuple(row.roles),
            )
            for row in rows
        }

    async def upsert(
        self,
        name: str,
        override: ToolOverride | None,
        *,
        updated_by: str,
        change: ToolSettingChange | None = None,
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            if override is None:
                await session.execute(delete(ToolSetting).where(ToolSetting.name == name))
            else:
                stmt = pg_insert(ToolSetting).values(
                    name=name,
                    enabled=override.enabled,
                    roles=None if override.roles is None else list(override.roles),
                    updated_by=updated_by,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["name"],
                    set_={
                        "enabled": stmt.excluded.enabled,
                        "roles": stmt.excluded.roles,
                        "updated_by": stmt.excluded.updated_by,
                        "updated_at": utcnow(),
                    },
                )
                await session.execute(stmt)
            if change is not None:
                session.add(self._change_row(change))

    async def replace(
        self,
        overrides: Mapping[str, ToolOverride],
        *,
        updated_by: str,
        changes: Sequence[ToolSettingChange] = (),
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(delete(ToolSetting))
            for name, override in overrides.items():
                await session.execute(
                    pg_insert(ToolSetting).values(
                        name=name,
                        enabled=override.enabled,
                        roles=None if override.roles is None else list(override.roles),
                        updated_by=updated_by,
                    )
                )
            for change in changes:
                session.add(self._change_row(change))

    async def history(self, name: str, *, limit: int = 20) -> list[ToolSettingChangeRecord]:
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(ToolSettingChangeRow)
                    .where(ToolSettingChangeRow.tool_name == name)
                    .order_by(
                        ToolSettingChangeRow.changed_at.desc(),
                        ToolSettingChangeRow.id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        return [
            ToolSettingChangeRecord(
                id=row.id,
                tool_name=row.tool_name,
                changed_by=row.changed_by,
                changed_at=row.changed_at,
                source=row.source,
                before=row.before,
                after=row.after,
            )
            for row in rows
        ]

    @staticmethod
    def _change_row(change: ToolSettingChange) -> ToolSettingChangeRow:
        return ToolSettingChangeRow(
            tool_name=change.tool_name,
            changed_by=change.changed_by,
            source=change.source,
            before=change.before,
            after=change.after,
        )


class ToolPolicy:
    def __init__(self, store: ToolSettingStore, *, ttl_s: float = POLICY_TTL_S) -> None:
        self._store = store
        self._ttl_s = ttl_s
        self._cached: dict[str, ToolOverride] | None = None
        self._loaded_at = 0.0
        # None = 没失败过；用时间戳作哨兵会在 monotonic 起点附近误判成「刚失败」
        self._failed_at: float | None = None
        self._lock = asyncio.Lock()

    async def overrides(
        self, *, force: bool = False, allow_stale: bool = True
    ) -> dict[str, ToolOverride]:
        """读取覆盖。

        `allow_stale=True` 供工具执行使用：库短暂不可用时保留上一份快照，
        避免所有工具调用一起失败。
        `allow_stale=False` 供管理页使用：读不到真实配置就报错，**不能**把
        空/旧快照当成现状再整表覆盖回去（会静默丢掉禁用/角色配置）。
        """
        now = monotonic()
        cached = self._cached
        if not force and cached is not None and now - self._loaded_at < self._ttl_s:
            return cached
        # 冷启动就遇到库故障时，2s 内不要每个工具调用都重试一次
        if (
            not force
            and allow_stale
            and cached is None
            and self._failed_at is not None
            and now - self._failed_at < self._ttl_s
        ):
            return {}
        async with self._lock:
            # 等锁期间可能已有别的协程刷新过
            now = monotonic()
            cached = self._cached
            if not force and cached is not None and now - self._loaded_at < self._ttl_s:
                return cached
            if (
                not force
                and allow_stale
                and cached is None
                and self._failed_at is not None
                and now - self._failed_at < self._ttl_s
            ):
                return {}
            try:
                loaded = await self._store.load()
            except Exception as exc:  # 库不可用
                log.warning("tool_policy_load_failed", error=str(exc))
                if not allow_stale:
                    raise
                self._failed_at = monotonic()
                return dict(self._cached or {})
            self._cached = loaded
            self._loaded_at = monotonic()
            self._failed_at = None
            return loaded

    async def apply(self, spec: ToolSpec) -> ToolSpec:
        override = (await self.overrides()).get(spec.name)
        return self.effective_spec(spec, override)

    @staticmethod
    def effective_spec(spec: ToolSpec, override: ToolOverride | None) -> ToolSpec:
        if override is None:
            return spec
        # 代码里禁用是硬边界：管理页只能进一步收紧，不能把未就绪工具放出来
        enabled = spec.enabled and (True if override.enabled is None else override.enabled)
        roles = spec.roles if override.roles is None else override.roles
        return replace(spec, enabled=enabled, roles=roles)

    async def override_for(self, name: str) -> ToolOverride | None:
        return (await self.overrides()).get(name)

    async def set_override(
        self,
        name: str,
        override: ToolOverride | None,
        *,
        updated_by: str = "system",
        change: ToolSettingChange | None = None,
    ) -> None:
        await self._store.upsert(name, override, updated_by=updated_by, change=change)
        self.invalidate()

    async def replace_overrides(
        self,
        overrides: Mapping[str, ToolOverride],
        *,
        updated_by: str = "system",
        changes: Sequence[ToolSettingChange] = (),
    ) -> None:
        await self._store.replace(overrides, updated_by=updated_by, changes=changes)
        self.invalidate()

    async def history(self, name: str, *, limit: int = 20) -> list[ToolSettingChangeRecord]:
        return await self._store.history(name, limit=limit)

    def invalidate(self) -> None:
        self._cached = None
        self._loaded_at = 0.0
        # 写入成功说明库已恢复：清掉失败退避，否则新配置会被 TTL 挡住 2s
        self._failed_at = None


_policy: ToolPolicy | None = None


def get_tool_policy() -> ToolPolicy:
    """进程级单例；API 与 Agent 运行时必须看到同一份覆盖。"""
    global _policy
    if _policy is None:
        store: ToolSettingStore
        if get_settings().store_backend == "postgres":
            store = PostgresToolSettingStore()
        else:
            store = InMemoryToolSettingStore()
        _policy = ToolPolicy(store)
    return _policy


def set_tool_policy(policy: ToolPolicy | None) -> None:
    """测试替换用；传 None 让下次按当前 settings 重建。"""
    global _policy
    _policy = policy
