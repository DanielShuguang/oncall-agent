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
from collections.abc import Sequence
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

#: 预扣超过这个时间仍未结算，就认为它泄漏了：模型请求超时是 20s（ADR-0013），
#: 留 15 倍余量。不新增环境变量，避免运维在报表里看到第二套阈值（ADR-0028）。
RESERVATION_STALE_S = 300.0

#: Redis reservations hash 里时间戳字段的后缀：`<token>:ts`。与金额写进同一个
#: hash，保证「预扣 + 时间」一次落盘；旧格式没有该字段，快照里 age 为 None。
_TS_SUFFIX = ":ts"


class LedgerUnavailable(RuntimeError):
    """账本快照读不到（Redis 故障）。

    管理页必须显式报错，不能拿内存兜底冒充现状：那会把「Redis 挂了」
    显示成「今天没花钱」。
    """


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    """一笔仍挂在账上的预扣；`age_s` 为 None 表示旧格式没有时间戳。"""

    token: str
    cents: int
    age_s: float | None


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    """某个 UTC 日的账本只读视图：已花费（含未结算预扣）+ 未结算明细。"""

    spent_cents: int
    reservations: tuple[ReservationSnapshot, ...]


def _snapshot_from_rows(
    spent_cents: int, rows: Sequence[tuple[str, int, float | None]]
) -> LedgerSnapshot:
    """按 token 排序，保证同一份账本两次快照的 JSON 顺序稳定（便于测试与 diff）。"""
    return LedgerSnapshot(
        spent_cents=spent_cents,
        reservations=tuple(
            ReservationSnapshot(token=token, cents=cents, age_s=age)
            for token, cents, age in sorted(rows, key=lambda row: row[0])
        ),
    )


def _parse_redis_snapshot(spent_raw: str | None, raw: dict[str, str]) -> LedgerSnapshot:
    now = time.time()
    rows: list[tuple[str, int, float | None]] = []
    for field, value in raw.items():
        if field.endswith(_TS_SUFFIX):
            continue
        ts_raw = raw.get(field + _TS_SUFFIX)
        age = None if ts_raw is None else max(0.0, now - float(ts_raw))
        rows.append((field, int(value), age))
    return _snapshot_from_rows(int(spent_raw or 0), rows)


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
    #: 按用户账本的预扣必须带上用户；全局账本为 None（ADR-0026）
    user_id: str | None = None


class BudgetLedger(Protocol):
    async def reserve(self, cents: int) -> BudgetReservation | None: ...

    async def settle(self, reservation: BudgetReservation, actual: int) -> None: ...

    async def spent(self) -> int: ...

    async def snapshot(self) -> LedgerSnapshot: ...

    async def close(self) -> None: ...


class UserBudgetLedger(Protocol):
    """按用户累计当日预扣；上限每次传入，因为覆盖表可以随时改（ADR-0026）。

    调用方保证 `limit_cents > 0`：0 表示不限，网关不会拿 0 来预扣。
    """

    async def reserve(
        self, user_id: str, cents: int, *, limit_cents: int
    ) -> BudgetReservation | None: ...

    async def settle(self, reservation: BudgetReservation, actual: int) -> None: ...

    async def spent(self, user_id: str) -> int: ...

    async def snapshot(self) -> dict[str, LedgerSnapshot]: ...

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
        #: token -> (预扣金额, 预扣时的 epoch 秒)，只用于管理页快照（ADR-0028）
        self._reservations: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, cents: int) -> BudgetReservation | None:
        if cents <= 0:
            return BudgetReservation(cents=0, backend="memory", day=_utc_day())
        async with self._lock:
            self._rollover()
            if self._spent + cents > self._limit:
                return None
            self._spent += cents
            token = uuid.uuid4().hex
            self._reservations[token] = (cents, time.time())
            return BudgetReservation(cents=cents, backend="memory", day=_utc_day(), token=token)

    async def settle(self, reservation: BudgetReservation, actual: int) -> None:
        async with self._lock:
            self._rollover()
            if reservation.token is not None:
                self._reservations.pop(reservation.token, None)
            self._spent = max(0, self._spent + actual - reservation.cents)

    async def spent(self) -> int:
        async with self._lock:
            self._rollover()
            return self._spent

    async def snapshot(self) -> LedgerSnapshot:
        async with self._lock:
            self._rollover()
            now = time.time()
            rows = [
                (token, cents, now - created)
                for token, (cents, created) in self._reservations.items()
            ]
            return _snapshot_from_rows(self._spent, rows)

    def _rollover(self) -> None:
        today = _utc_day()
        if today != self._day:
            self._day = today
            self._spent = 0
            self._reservations.clear()

    async def close(self) -> None:
        return None


class RedisBudgetLedger:
    _RESERVE_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local token = ARGV[4]
local now = ARGV[5]
if current + amount > limit then return 0 end
redis.call('INCRBY', KEYS[1], amount)
redis.call('HSET', KEYS[2], token, amount)
redis.call('HSET', KEYS[2], token .. ':ts', now)
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)
if KEYS[3] then
  redis.call('SADD', KEYS[3], ARGV[6])
  redis.call('EXPIRE', KEYS[3], ttl)
end
return 1
"""

    #: 结算必须按凭证里的 reserved 金额回冲；凭证过期/Redis 重启时按 0 处理，
    #: 只把实际花费加回去，避免把别人的预扣减成负数。
    _SETTLE_SCRIPT = """
local reserved = tonumber(redis.call('HGET', KEYS[2], ARGV[1]) or '0')
local actual = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1] .. ':ts')
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
        return _budget_ttl()

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
                int(time.time()),
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

    async def snapshot(self) -> LedgerSnapshot:
        try:
            pipe = self._redis().pipeline(transaction=False)
            pipe.get(self._key())
            pipe.hgetall(self._reservations_key())
            spent_raw, raw = await pipe.execute()
        except Exception as exc:
            log.warning("budget_snapshot_failed", error=str(exc))
            raise LedgerUnavailable("预算账本暂不可用") from exc
        return _parse_redis_snapshot(spent_raw, raw)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _utc_day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def budget_day() -> str:
    """管理页展示用的当前 UTC 日；账本内部仍用 `_utc_day()`。"""
    return _utc_day()


def _budget_ttl() -> int:
    """日账 key 的过期时间：跨过 UTC 零点再多留 1 小时，容忍时钟偏差。"""
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow - now).total_seconds()) + 3600)


class InMemoryUserBudgetLedger:
    """按用户累计当日预扣；上限每次传入（覆盖表可以随时改，ADR-0026）。"""

    def __init__(self) -> None:
        self._spent: dict[str, int] = {}
        #: token -> (user_id, 预扣金额, 预扣时的 epoch 秒)，只用于管理页快照（ADR-0028）
        self._reservations: dict[str, tuple[str, int, float]] = {}
        self._day = _utc_day()
        self._lock = asyncio.Lock()

    async def reserve(
        self, user_id: str, cents: int, *, limit_cents: int
    ) -> BudgetReservation | None:
        if cents <= 0:
            return BudgetReservation(cents=0, backend="memory", day=_utc_day(), user_id=user_id)
        async with self._lock:
            self._rollover()
            current = self._spent.get(user_id, 0)
            if current + cents > limit_cents:
                return None
            self._spent[user_id] = current + cents
            token = uuid.uuid4().hex
            self._reservations[token] = (user_id, cents, time.time())
            return BudgetReservation(
                cents=cents,
                backend="memory",
                day=_utc_day(),
                token=token,
                user_id=user_id,
            )

    async def settle(self, reservation: BudgetReservation, actual: int) -> None:
        user_id = reservation.user_id
        if user_id is None:  # 账本之间不能串用凭证
            raise ValueError("用户预算凭证缺少 user_id")
        async with self._lock:
            self._rollover()
            if reservation.token is not None:
                self._reservations.pop(reservation.token, None)
            current = self._spent.get(user_id, 0)
            self._spent[user_id] = max(0, current + actual - reservation.cents)

    async def spent(self, user_id: str) -> int:
        async with self._lock:
            self._rollover()
            return self._spent.get(user_id, 0)

    async def snapshot(self) -> dict[str, LedgerSnapshot]:
        async with self._lock:
            self._rollover()
            now = time.time()
            users = set(self._spent) | {user for user, _, _ in self._reservations.values()}
            snapshots: dict[str, LedgerSnapshot] = {}
            for user_id in sorted(users):
                rows = [
                    (token, cents, now - created)
                    for token, (owner, cents, created) in self._reservations.items()
                    if owner == user_id
                ]
                snapshots[user_id] = _snapshot_from_rows(self._spent.get(user_id, 0), rows)
            return snapshots

    def _rollover(self) -> None:
        today = _utc_day()
        if today != self._day:
            self._day = today
            self._spent = {}
            self._reservations.clear()

    async def close(self) -> None:
        return None


class RedisUserBudgetLedger:
    """与全局账本同构的 Lua 脚本，只是 key 带用户；上限来自 ARGV。"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis | None = None
        self._fallback = InMemoryUserBudgetLedger()

    def _redis(self) -> Redis:
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    def _key(self, user_id: str, day: str | None = None) -> str:
        return f"oncall:budget:user:{user_id}:{day or _utc_day()}"

    def _reservations_key(self, user_id: str, day: str | None = None) -> str:
        return f"oncall:budget:user:reservations:{user_id}:{day or _utc_day()}"

    def _users_key(self, day: str | None = None) -> str:
        """当日有预扣的用户集合；管理页用它枚举用户，避免 SCAN 误匹配 reservations key。"""
        return f"oncall:budget:users:{day or _utc_day()}"

    async def reserve(
        self, user_id: str, cents: int, *, limit_cents: int
    ) -> BudgetReservation | None:
        day = _utc_day()
        if cents <= 0:
            return BudgetReservation(cents=0, backend="redis", day=day, user_id=user_id)
        token = uuid.uuid4().hex
        try:
            result = await self._redis().eval(
                RedisBudgetLedger._RESERVE_SCRIPT,
                3,
                self._key(user_id, day),
                self._reservations_key(user_id, day),
                self._users_key(day),
                limit_cents,
                cents,
                _budget_ttl(),
                token,
                int(time.time()),
                user_id,
            )
            if not int(result):
                return None
            return BudgetReservation(
                cents=cents,
                backend="redis",
                day=day,
                token=token,
                user_id=user_id,
            )
        except Exception as exc:
            log.warning("user_budget_redis_failed", error=str(exc), user_id=user_id)
            # 内存预扣返回的凭证 backend=memory；结算不会再去碰 Redis
            return await self._fallback.reserve(user_id, cents, limit_cents=limit_cents)

    async def settle(self, reservation: BudgetReservation, actual: int) -> None:
        user_id = reservation.user_id
        if user_id is None:
            raise ValueError("用户预算凭证缺少 user_id")
        if reservation.backend == "memory":
            await self._fallback.settle(reservation, actual)
            return
        day = reservation.day or _utc_day()
        if reservation.token is None:
            if actual <= 0:
                return
            try:
                await self._redis().incrby(self._key(user_id, day), actual)
                await self._redis().expire(self._key(user_id, day), _budget_ttl())
            except Exception as exc:
                log.warning("user_budget_settle_failed", error=str(exc), user_id=user_id)
            return
        try:
            await self._redis().eval(
                RedisBudgetLedger._SETTLE_SCRIPT,
                2,
                self._key(user_id, day),
                self._reservations_key(user_id, day),
                reservation.token,
                actual,
                _budget_ttl(),
            )
        except Exception as exc:
            # 与全局账本同一种取舍：不降级到内存，最多让当天额度偏保守
            log.warning(
                "user_budget_settle_failed_left_reserved",
                error=str(exc),
                user_id=user_id,
                reserved=reservation.cents,
            )

    async def spent(self, user_id: str) -> int:
        try:
            value = await self._redis().get(self._key(user_id))
            return int(value or 0)
        except Exception as exc:
            log.warning("user_budget_read_failed", error=str(exc), user_id=user_id)
            return await self._fallback.spent(user_id)

    async def snapshot(self) -> dict[str, LedgerSnapshot]:
        day = _utc_day()
        try:
            raw_users = await self._redis().smembers(self._users_key(day))
            users = sorted(user.decode() if isinstance(user, bytes) else user for user in raw_users)
            if not users:
                return {}
            pipe = self._redis().pipeline(transaction=False)
            for user_id in users:
                pipe.get(self._key(user_id, day))
                pipe.hgetall(self._reservations_key(user_id, day))
            results = await pipe.execute()
        except Exception as exc:
            log.warning("user_budget_snapshot_failed", error=str(exc))
            raise LedgerUnavailable("用户预算账本暂不可用") from exc
        snapshots: dict[str, LedgerSnapshot] = {}
        for index, user_id in enumerate(users):
            snapshots[user_id] = _parse_redis_snapshot(results[index * 2], results[index * 2 + 1])
        return snapshots

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_rate_limiter: RateLimiter | None = None
_budget_ledger: BudgetLedger | None = None
_user_budget_ledger: UserBudgetLedger | None = None


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.store_backend == "postgres":
        return RedisRateLimiter(settings.redis_url, settings.rate_limit_per_min)
    return InMemoryRateLimiter(settings.rate_limit_per_min)


def build_budget_ledger(settings: Settings) -> BudgetLedger:
    if settings.store_backend == "postgres":
        return RedisBudgetLedger(settings.redis_url, settings.daily_budget_cents)
    return InMemoryBudgetLedger(settings.daily_budget_cents)


def build_user_budget_ledger(settings: Settings) -> UserBudgetLedger:
    if settings.store_backend == "postgres":
        return RedisUserBudgetLedger(settings.redis_url)
    return InMemoryUserBudgetLedger()


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


def get_user_budget_ledger() -> UserBudgetLedger:
    global _user_budget_ledger
    if _user_budget_ledger is None:
        from app.core.config import get_settings

        _user_budget_ledger = build_user_budget_ledger(get_settings())
    return _user_budget_ledger


def set_user_budget_ledger(value: UserBudgetLedger | None) -> None:
    """测试钩子。"""
    global _user_budget_ledger
    _user_budget_ledger = value
