"""限流与预算（W4 D17）。

- 限流：按用户滑动窗口，默认 `ONCALL_RATE_LIMIT_PER_MIN=30` 次/分钟
- 预算：按 UTC 自然日累计，单位「分」；模型调用前预扣、返回后按实际结算
- Redis 是首选实现；Redis 不可用时退化为进程内窗口并打 warning ——
  宁可限流/预算只在单实例生效，也不能让聊天接口 500

为什么不用固定窗口：`INCR + EXPIRE` 在窗口边界会放过 2 倍流量；
滑动窗口用 ZSET/双端队列，边界更准。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from app.core.config import Settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)

RATE_LIMIT_WINDOW_S = 60.0


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool: ...

    async def close(self) -> None: ...


class BudgetLedger(Protocol):
    async def reserve(self, cents: int) -> bool: ...

    async def settle(self, reserved: int, actual: int) -> None: ...

    async def spent(self) -> int: ...

    async def close(self) -> None: ...


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_s: float = RATE_LIMIT_WINDOW_S) -> None:
        self._limit = limit
        self._window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self._window_s
        async with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    async def close(self) -> None:
        return None


class RedisRateLimiter:
    _SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then return 0 end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window + 1000)
return 1
"""

    def __init__(self, url: str, limit: int, window_s: float = RATE_LIMIT_WINDOW_S) -> None:
        self._url = url
        self._limit = limit
        self._window_s = window_s
        self._client: Redis | None = None
        self._fallback = InMemoryRateLimiter(limit, window_s)

    def _redis(self) -> Redis:
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    async def allow(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        try:
            client = self._redis()
            result = await client.eval(
                self._SCRIPT,
                1,
                f"oncall:rate:{key}",
                int(time.time() * 1000),
                int(self._window_s * 1000),
                self._limit,
                f"{time.time_ns()}-{uuid.uuid4().hex[:6]}",
            )
            return bool(int(result))
        except Exception as exc:  # Redis 挂掉不能阻断聊天
            log.warning("rate_limit_redis_failed", error=str(exc))
            return await self._fallback.allow(key)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class InMemoryBudgetLedger:
    def __init__(self, limit_cents: int) -> None:
        self._limit = limit_cents
        self._spent = 0
        self._day = _utc_day()
        self._lock = asyncio.Lock()

    async def reserve(self, cents: int) -> bool:
        if cents <= 0:
            return True
        async with self._lock:
            self._rollover()
            if self._spent + cents > self._limit:
                return False
            self._spent += cents
            return True

    async def settle(self, reserved: int, actual: int) -> None:
        async with self._lock:
            self._rollover()
            self._spent = max(0, self._spent + actual - reserved)

    async def spent(self) -> int:
        async with self._lock:
            self._rollover()
            return self._spent

    def _rollover(self) -> None:
        today = _utc_day()
        if today != self._day:
            self._day = today
            self._spent = 0

    async def close(self) -> None:
        return None


class RedisBudgetLedger:
    _RESERVE_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if current + amount > limit then return 0 end
redis.call('INCRBY', KEYS[1], amount)
redis.call('EXPIRE', KEYS[1], ttl)
return 1
"""

    def __init__(self, url: str, limit_cents: int) -> None:
        self._url = url
        self._limit = limit_cents
        self._client: Redis | None = None
        self._fallback = InMemoryBudgetLedger(limit_cents)

    def _redis(self) -> Redis:
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    def _key(self) -> str:
        return f"oncall:budget:{_utc_day()}"

    def _ttl(self) -> int:
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((tomorrow - now).total_seconds()) + 3600)

    async def reserve(self, cents: int) -> bool:
        if cents <= 0:
            return True
        try:
            result = await self._redis().eval(
                self._RESERVE_SCRIPT,
                1,
                self._key(),
                self._limit,
                cents,
                self._ttl(),
            )
            return bool(int(result))
        except Exception as exc:
            log.warning("budget_redis_failed", error=str(exc))
            return await self._fallback.reserve(cents)

    async def settle(self, reserved: int, actual: int) -> None:
        delta = actual - reserved
        if delta == 0:
            return
        try:
            await self._redis().incrby(self._key(), delta)
            await self._redis().expire(self._key(), self._ttl())
        except Exception as exc:
            log.warning("budget_settle_failed", error=str(exc))
            await self._fallback.settle(reserved, actual)

    async def spent(self) -> int:
        try:
            value = await self._redis().get(self._key())
            return int(value or 0)
        except Exception as exc:
            log.warning("budget_read_failed", error=str(exc))
            return await self._fallback.spent()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _utc_day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


_rate_limiter: RateLimiter | None = None
_budget_ledger: BudgetLedger | None = None


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.store_backend == "postgres":
        return RedisRateLimiter(settings.redis_url, settings.rate_limit_per_min)
    return InMemoryRateLimiter(settings.rate_limit_per_min)


def build_budget_ledger(settings: Settings) -> BudgetLedger:
    if settings.store_backend == "postgres":
        return RedisBudgetLedger(settings.redis_url, settings.daily_budget_cents)
    return InMemoryBudgetLedger(settings.daily_budget_cents)


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        from app.core.config import get_settings

        _rate_limiter = build_rate_limiter(get_settings())
    return _rate_limiter


def get_budget_ledger() -> BudgetLedger:
    global _budget_ledger
    if _budget_ledger is None:
        from app.core.config import get_settings

        _budget_ledger = build_budget_ledger(get_settings())
    return _budget_ledger


def set_rate_limiter(value: RateLimiter | None) -> None:
    """测试钩子。"""
    global _rate_limiter
    _rate_limiter = value


def set_budget_ledger(value: BudgetLedger | None) -> None:
    """测试钩子。"""
    global _budget_ledger
    _budget_ledger = value
