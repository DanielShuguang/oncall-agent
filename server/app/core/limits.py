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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol

from app.core.config import Settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)

RATE_LIMIT_WINDOW_S = 60.0

BudgetBackend = Literal["redis", "memory"]


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    """一次预算预扣的凭证；必须回到预扣时的同一个后端结算。

    `backend` 不是诊断信息：Redis 预扣失败退到内存后，结算若又走 Redis，
    会把从未在 Redis 记过的 `reserved` 减掉，造成日预算负数或串账。
    """

    cents: int
    backend: BudgetBackend
    #: 预扣所属的 UTC 日；跨日结算仍写回预扣当天，避免把 23:59 的成本记到次日
    day: str | None = None
    #: Redis 预扣在 reservations hash 里的键；内存预扣为 None
    token: str | None = None


class BudgetLedger(Protocol):
    async def reserve(self, cents: int) -> BudgetReservation | None: ...

    async def settle(self, reservation: BudgetReservation, actual: int) -> None: ...

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

    async def reserve(self, cents: int) -> BudgetReservation | None:
        if cents <= 0:
            return BudgetReservation(cents=0, backend="memory", day=_utc_day())
        async with self._lock:
            self._rollover()
            if self._spent + cents > self._limit:
                return None
            self._spent += cents
            return BudgetReservation(cents=cents, backend="memory", day=_utc_day())

    async def settle(self, reservation: BudgetReservation, actual: int) -> None:
        async with self._lock:
            self._rollover()
            self._spent = max(0, self._spent + actual - reservation.cents)

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
local token = ARGV[4]
if current + amount > limit then return 0 end
redis.call('INCRBY', KEYS[1], amount)
redis.call('HSET', KEYS[2], token, amount)
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)
return 1
"""

    #: 结算必须按凭证里的 reserved 金额回冲；凭证过期/Redis 重启时按 0 处理，
    #: 只把实际花费加回去，避免把别人的预扣减成负数。
    _SETTLE_SCRIPT = """
local reserved = tonumber(redis.call('HGET', KEYS[2], ARGV[1]) or '0')
local actual = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if reserved > 0 then redis.call('HDEL', KEYS[2], ARGV[1]) end
local delta = actual - reserved
if delta ~= 0 then redis.call('INCRBY', KEYS[1], delta) end
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current < 0 then redis.call('SET', KEYS[1], 0) end
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)
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

    def _key(self, day: str | None = None) -> str:
        return f"oncall:budget:{day or _utc_day()}"

    def _reservations_key(self, day: str | None = None) -> str:
        return f"oncall:budget:reservations:{day or _utc_day()}"

    def _ttl(self) -> int:
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((tomorrow - now).total_seconds()) + 3600)

    async def reserve(self, cents: int) -> BudgetReservation | None:
        day = _utc_day()
        if cents <= 0:
            return BudgetReservation(cents=0, backend="redis", day=day)
        token = uuid.uuid4().hex
        try:
            result = await self._redis().eval(
                self._RESERVE_SCRIPT,
                2,
                self._key(day),
                self._reservations_key(day),
                self._limit,
                cents,
                self._ttl(),
                token,
            )
            if not int(result):
                return None
            return BudgetReservation(cents=cents, backend="redis", day=day, token=token)
        except Exception as exc:
            log.warning("budget_redis_failed", error=str(exc))
            # 内存预扣返回的凭证 backend=memory；结算不会再去碰 Redis
            return await self._fallback.reserve(cents)

    async def settle(self, reservation: BudgetReservation, actual: int) -> None:
        if reservation.backend == "memory":
            await self._fallback.settle(reservation, actual)
            return
        day = reservation.day or _utc_day()
        if reservation.token is None:
            # 0 预扣不需要凭证；只有实际花费时才补记一笔
            if actual <= 0:
                return
            try:
                await self._redis().incrby(self._key(day), actual)
                await self._redis().expire(self._key(day), self._ttl())
            except Exception as exc:
                log.warning("budget_settle_failed", error=str(exc))
            return
        try:
            await self._redis().eval(
                self._SETTLE_SCRIPT,
                2,
                self._key(day),
                self._reservations_key(day),
                reservation.token,
                actual,
                self._ttl(),
            )
        except Exception as exc:
            # 不降级到内存：那会把 Redis 里的预扣留在账上，同时再记一次内存账。
            # 保留预扣最多让当天预算偏保守，日切后自然清零。
            log.warning(
                "budget_settle_failed_left_reserved",
                error=str(exc),
                reserved=reservation.cents,
            )

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
