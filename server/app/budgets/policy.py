"""用户日预算策略：环境默认值 + 表覆盖 + 短 TTL 缓存（ADR-0026）。

网关在**每次模型调用前**读一次上限，所以读取必须便宜：整表读进内存，
2 秒内复用（与工具覆盖同一种取舍，多副本部署时改完最多 2s 生效）。

读库失败时退回默认值与上一份快照，而不是让聊天 500：预算闸门的定位是
「别把钱花超」，全局日预算仍独立生效；真正的边界在 `core/limits.py` 的账本。
"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Protocol

from app.budgets.store import (
    InMemoryUserBudgetStore,
    PostgresUserBudgetStore,
    UserBudgetOverride,
    UserBudgetStore,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: 多副本部署时管理员改完限额最多这么久生效；单进程写后会 invalidate 立即生效
BUDGET_POLICY_TTL_S = 2.0


class BudgetLimitProvider(Protocol):
    """网关只需要「这个用户今天最多花多少分」。"""

    async def limit_for(self, user_id: str) -> int: ...


class UserBudgetPolicy:
    def __init__(
        self,
        store: UserBudgetStore,
        *,
        default_cents: int = 0,
        ttl_s: float = BUDGET_POLICY_TTL_S,
    ) -> None:
        self._store = store
        self._default_cents = default_cents
        self._ttl_s = ttl_s
        self._cached: dict[str, UserBudgetOverride] | None = None
        self._loaded_at = 0.0
        # None = 没失败过；用时间戳作哨兵会在 monotonic 起点附近误判成「刚失败」
        self._failed_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def default_cents(self) -> int:
        return self._default_cents

    async def limit_for(self, user_id: str) -> int:
        """该用户今天的上限（分）；0 = 不限。覆盖优先于环境默认值。"""
        override = (await self.overrides()).get(user_id)
        return self._default_cents if override is None else override.daily_cents

    async def overrides(
        self, *, force: bool = False, allow_stale: bool = True
    ) -> dict[str, UserBudgetOverride]:
        """读取覆盖表。

        `allow_stale=True` 供网关使用：库短暂不可用时保留上一份快照；
        `allow_stale=False` 供管理页使用：读不到真实配置就报错，不能把旧快照当现状。
        """
        now = monotonic()
        cached = self._cached
        if not force and cached is not None and now - self._loaded_at < self._ttl_s:
            return cached
        # 冷启动就遇到库故障时，TTL 内不要每个模型调用都重试一次
        if (
            not force
            and allow_stale
            and cached is None
            and self._failed_at is not None
            and now - self._failed_at < self._ttl_s
        ):
            return {}
        async with self._lock:
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
                log.warning("user_budget_load_failed", error=str(exc))
                if not allow_stale:
                    raise
                self._failed_at = monotonic()
                return dict(self._cached or {})
            self._cached = loaded
            self._loaded_at = monotonic()
            self._failed_at = None
            return loaded

    async def set_limit(
        self, user_id: str, daily_cents: int, *, updated_by: str
    ) -> UserBudgetOverride:
        await self._store.upsert(user_id, daily_cents, updated_by=updated_by)
        self.invalidate()
        return UserBudgetOverride(
            user_id=user_id,
            daily_cents=daily_cents,
            updated_by=updated_by,
        )

    async def clear(self, user_id: str) -> None:
        """删掉覆盖，回到环境默认值；0 分的覆盖要用 `set_limit(0)` 而不是删除。"""
        await self._store.delete(user_id)
        self.invalidate()

    def invalidate(self) -> None:
        self._cached = None
        self._loaded_at = 0.0
        # 写入成功说明库已恢复：清掉失败退避，否则新限额会被 TTL 挡住 2s
        self._failed_at = None


_policy: UserBudgetPolicy | None = None


def build_user_budget_policy(settings: Settings | None = None) -> UserBudgetPolicy:
    """按配置建策略；测试可传 settings 或直接构造。"""
    resolved = settings or get_settings()
    store: UserBudgetStore
    if resolved.store_backend == "postgres":
        store = PostgresUserBudgetStore()
    else:
        store = InMemoryUserBudgetStore()
    return UserBudgetPolicy(store, default_cents=resolved.user_daily_budget_cents)


def get_user_budget_policy() -> UserBudgetPolicy:
    """进程级单例；管理接口与网关必须看到同一份覆盖。"""
    global _policy
    if _policy is None:
        _policy = build_user_budget_policy()
    return _policy


def set_user_budget_policy(policy: UserBudgetPolicy | None) -> None:
    """测试替换用；传 None 让下次按当前 settings 重建。"""
    global _policy
    _policy = policy
