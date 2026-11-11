"""按用户日预算：账本、策略、管理接口与网关闸门（ADR-0026）。

判定口径全部是「分」整数、UTC 自然日：先预扣、后按实际结算，超限在模型调用**之前**
拒绝。Postgres 存取契约在 `test_budgets_pg.py`；Redis 账本用例需要
`ONCALL_TEST_REDIS_URL`，没有就跳过（本地用 compose 里的 redis）。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.budgets.policy import (
    UserBudgetPolicy,
    build_user_budget_policy,
    get_user_budget_policy,
    set_user_budget_policy,
)
from app.budgets.store import InMemoryUserBudgetStore, UserBudgetOverride
from app.core.config import Settings
from app.core.limits import (
    BudgetReservation,
    InMemoryBudgetLedger,
    InMemoryUserBudgetLedger,
    RedisUserBudgetLedger,
)
from app.gateway.gateway import ModelGateway
from app.gateway.meter import InMemoryModelCallStore
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    ModelUnavailable,
    ProviderError,
    Purpose,
    RawCompletion,
    Route,
)
from tests.support import auth_headers

CLOUD = Route(
    provider="cloud",
    model="gpt-test",
    base_url="http://cloud",
    api_key="k",
    price_in_cents_per_1m=15,
    price_out_cents_per_1m=60,
    timeout_s=1.0,
)

ADMIN = auth_headers("admin_1", ("admin",))


# --------------------------------------------------------------------------- #
# 账本
# --------------------------------------------------------------------------- #


async def test_in_memory_user_ledger_reserves_settles_and_isolates() -> None:
    ledger = InMemoryUserBudgetLedger()
    first = await ledger.reserve("u_1", 6, limit_cents=10)
    assert first is not None
    assert first.user_id == "u_1"
    # 同一用户再预扣 6 会超过 10 分
    assert await ledger.reserve("u_1", 6, limit_cents=10) is None
    # 其他用户互不影响
    assert await ledger.reserve("u_2", 6, limit_cents=10) is not None

    await ledger.settle(first, 2)
    assert await ledger.spent("u_1") == 2
    assert await ledger.spent("u_2") == 6
    # 结算后腾出的额度可以继续用
    assert await ledger.reserve("u_1", 8, limit_cents=10) is not None


async def test_in_memory_user_ledger_resets_on_utc_day_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import limits as limits_module

    monkeypatch.setattr(limits_module, "_utc_day", lambda: "2026-11-11")
    ledger = InMemoryUserBudgetLedger()
    assert await ledger.reserve("u_1", 10, limit_cents=10) is not None
    assert await ledger.reserve("u_1", 1, limit_cents=10) is None

    monkeypatch.setattr(limits_module, "_utc_day", lambda: "2026-11-12")
    assert await ledger.spent("u_1") == 0
    assert await ledger.reserve("u_1", 10, limit_cents=10) is not None


async def test_user_ledger_rejects_reservation_without_user() -> None:
    """凭证不能跨账本串用：全局预扣没有 user_id，用户账本必须拒绝。"""
    ledger = InMemoryUserBudgetLedger()
    with pytest.raises(ValueError):
        await ledger.settle(BudgetReservation(cents=5, backend="memory"), 1)


async def test_redis_user_ledger_falls_back_to_memory_when_redis_down() -> None:
    class BrokenRedis:
        async def eval(self, *args: Any, **kwargs: Any) -> int:
            raise RuntimeError("redis down")

        async def get(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("redis down")

        async def aclose(self) -> None:
            return None

    ledger = RedisUserBudgetLedger("redis://unused")
    assert "u_102" in ledger._key("u_102")
    assert "u_102" in ledger._reservations_key("u_102")

    ledger._redis = lambda: BrokenRedis()  # type: ignore[method-assign]
    reservation = await ledger.reserve("u_102", 5, limit_cents=10)
    assert reservation is not None
    assert reservation.backend == "memory"

    await ledger.settle(reservation, 2)
    assert await ledger.spent("u_102") == 2


@pytest.mark.skipif(
    not os.environ.get("ONCALL_TEST_REDIS_URL"),
    reason="需要 ONCALL_TEST_REDIS_URL 指向一个可清空的测试 redis",
)
async def test_redis_user_ledger_roundtrip() -> None:
    ledger = RedisUserBudgetLedger(os.environ["ONCALL_TEST_REDIS_URL"])
    user = f"test_{uuid.uuid4().hex[:10]}"
    try:
        first = await ledger.reserve(user, 5, limit_cents=8)
        assert first is not None and first.backend == "redis"
        assert await ledger.reserve(user, 5, limit_cents=8) is None

        await ledger.settle(first, 2)
        assert await ledger.spent(user) == 2
        # 2 + 6 = 8，正好用满
        second = await ledger.reserve(user, 6, limit_cents=8)
        assert second is not None
        await ledger.settle(second, 0)
        assert await ledger.spent(user) == 2
    finally:
        client = ledger._redis()
        await client.delete(
            ledger._key(user),
            ledger._reservations_key(user),
            ledger._users_key(),
        )
        await ledger.close()


# --------------------------------------------------------------------------- #
# 策略：默认值 + 覆盖 + 缓存
# --------------------------------------------------------------------------- #


class _CountingStore(InMemoryUserBudgetStore):
    def __init__(self) -> None:
        super().__init__()
        self.loads = 0

    async def load(self) -> dict[str, UserBudgetOverride]:
        self.loads += 1
        return await super().load()


class _FlakyStore(_CountingStore):
    def __init__(self) -> None:
        super().__init__()
        self.broken = False

    async def load(self) -> dict[str, UserBudgetOverride]:
        if self.broken:
            self.loads += 1
            raise RuntimeError("db down")
        return await super().load()


async def test_policy_default_override_and_clear() -> None:
    policy = UserBudgetPolicy(InMemoryUserBudgetStore(), default_cents=200, ttl_s=0)
    assert await policy.limit_for("u_1") == 200

    await policy.set_limit("u_1", 0, updated_by="admin_1")
    # 0 是显式的「该用户不限」，与「没有覆盖、继承 200」不同
    assert await policy.limit_for("u_1") == 0
    override = (await policy.overrides())["u_1"]
    assert override.daily_cents == 0
    assert override.updated_by == "admin_1"
    # 内存实现也要写时间：管理页 PUT 后直接回读，不能显示成 "-"
    assert override.updated_at is not None

    await policy.set_limit("u_2", 50, updated_by="admin_1")
    assert await policy.limit_for("u_2") == 50
    await policy.clear("u_2")
    assert await policy.limit_for("u_2") == 200


async def test_policy_caches_until_ttl_or_invalidate() -> None:
    store = _CountingStore()
    policy = UserBudgetPolicy(store, default_cents=0, ttl_s=60)
    await policy.limit_for("u_1")
    await policy.limit_for("u_1")
    assert store.loads == 1

    # 写成功立即失效：否则多副本/单进程都要等 TTL 才看到新限额
    await policy.set_limit("u_1", 30, updated_by="admin_1")
    assert await policy.limit_for("u_1") == 30
    assert store.loads == 2

    await policy.overrides(force=True)
    assert store.loads == 3


async def test_policy_keeps_stale_snapshot_on_store_failure() -> None:
    store = _FlakyStore()
    policy = UserBudgetPolicy(store, default_cents=0, ttl_s=0)
    await policy.set_limit("u_1", 30, updated_by="admin_1")
    assert await policy.limit_for("u_1") == 30

    store.broken = True
    # 网关路径保留上一份快照，不让聊天 500
    assert await policy.limit_for("u_1") == 30
    # 管理页不能把旧快照当现状
    with pytest.raises(RuntimeError):
        await policy.overrides(allow_stale=False)


def test_build_policy_maps_settings() -> None:
    """生产装配：环境默认值进策略、内存部署用内存存储（避免测试/演示连库）。"""
    policy = build_user_budget_policy(_settings(store_backend="memory", user_daily_budget_cny=0.5))
    assert policy.default_cents == 50


# --------------------------------------------------------------------------- #
# 管理接口
# --------------------------------------------------------------------------- #


async def test_budget_api_requires_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/admin/budgets")).status_code == 403
    res = await client.put(
        "/api/admin/budgets/u_205",
        json={"daily_cents": 100},
        headers=auth_headers(),
    )
    assert res.status_code == 403


async def test_budget_api_set_list_and_clear(client: AsyncClient) -> None:
    created = await client.put("/api/admin/budgets/u_205", json={"daily_cents": 120}, headers=ADMIN)
    assert created.status_code == 200
    body = created.json()
    assert body["user_id"] == "u_205"
    assert body["daily_cents"] == 120
    assert body["updated_by"] == "admin_1"

    listed = (await client.get("/api/admin/budgets", headers=ADMIN)).json()
    assert listed["default_cents"] == 0
    assert [item["user_id"] for item in listed["overrides"]] == ["u_205"]

    # 覆盖可以改成 0 = 不限
    updated = await client.put("/api/admin/budgets/u_205", json={"daily_cents": 0}, headers=ADMIN)
    assert updated.json()["daily_cents"] == 0

    cleared = await client.delete("/api/admin/budgets/u_205", headers=ADMIN)
    assert cleared.status_code == 204
    assert (await client.get("/api/admin/budgets", headers=ADMIN)).json()["overrides"] == []
    # 删除不存在的覆盖也是 204（幂等）
    assert (await client.delete("/api/admin/budgets/u_205", headers=ADMIN)).status_code == 204


async def test_budget_api_delete_falls_back_to_default(client: AsyncClient) -> None:
    """删除覆盖回到默认值；写 0 是"显式不限"，两者不能混。"""
    set_user_budget_policy(UserBudgetPolicy(InMemoryUserBudgetStore(), default_cents=120, ttl_s=0))
    listed = (await client.get("/api/admin/budgets", headers=ADMIN)).json()
    assert listed["default_cents"] == 120

    saved = await client.put("/api/admin/budgets/u_205", json={"daily_cents": 30}, headers=ADMIN)
    assert saved.json()["updated_at"] is not None
    policy = get_user_budget_policy()
    assert await policy.limit_for("u_205") == 30
    assert await policy.limit_for("u_206") == 120

    await client.delete("/api/admin/budgets/u_205", headers=ADMIN)
    assert await get_user_budget_policy().limit_for("u_205") == 120


@pytest.mark.parametrize("cents", [-1, 1_000_001])
async def test_budget_api_rejects_out_of_range(client: AsyncClient, cents: int) -> None:
    res = await client.put("/api/admin/budgets/u_1", json={"daily_cents": cents}, headers=ADMIN)
    assert res.status_code == 422


async def test_budget_api_rejects_user_id_with_space(client: AsyncClient) -> None:
    res = await client.put("/api/admin/budgets/u%20102", json={"daily_cents": 100}, headers=ADMIN)
    assert res.status_code == 422


async def test_budget_api_returns_503_when_store_unavailable(client: AsyncClient) -> None:
    class BrokenStore(InMemoryUserBudgetStore):
        async def load(self) -> dict[str, UserBudgetOverride]:
            raise SQLAlchemyError("db down")

    set_user_budget_policy(UserBudgetPolicy(BrokenStore(), default_cents=0, ttl_s=0))
    res = await client.get("/api/admin/budgets", headers=ADMIN)
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# 网关闸门
# --------------------------------------------------------------------------- #


class _FakeLimits:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.calls: list[str] = []

    async def limit_for(self, user_id: str) -> int:
        self.calls.append(user_id)
        return self.limit


class _FakeProvider:
    def __init__(self, result: RawCompletion | Exception) -> None:
        self.result = result
        self.calls = 0

    async def chat(
        self,
        messages: object,
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> RawCompletion:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _CountingUserLedger(InMemoryUserBudgetLedger):
    def __init__(self) -> None:
        super().__init__()
        self.reserve_calls = 0

    async def reserve(self, user_id: str, cents: int, *, limit_cents: int) -> Any:
        self.reserve_calls += 1
        return await super().reserve(user_id, cents, limit_cents=limit_cents)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "store_backend": "memory",
        "mock_mode": False,
        "model_max_tokens": 100,
        "run_budget_cents": 50,
        "daily_budget_cny": 5,
        "user_daily_budget_cny": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _gateway(
    *,
    budget_cents: int = 1000,
    user_limit: int = 1,
    user_ledger: InMemoryUserBudgetLedger | None = None,
    provider_result: RawCompletion | Exception | None = None,
) -> tuple[ModelGateway, InMemoryBudgetLedger, InMemoryUserBudgetLedger, _FakeProvider]:
    ledger = InMemoryBudgetLedger(budget_cents)
    budgets = user_ledger or InMemoryUserBudgetLedger()
    provider = _FakeProvider(provider_result or RawCompletion("ok", 100, 20))
    gateway = ModelGateway(
        [CLOUD],
        budget=ledger,
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: provider,
        user_budget=budgets,
        user_limits=_FakeLimits(user_limit),
    )
    return gateway, ledger, budgets, provider


async def _chat(gateway: ModelGateway, user_id: str = "u_102") -> None:
    await gateway.chat(
        [ChatMessage(role="user", content="hi")],
        purpose=Purpose.PLAN,
        run_id="r1",
        step="plan",
        user_id=user_id,
    )


async def test_user_budget_rejects_before_calling_provider_and_releases_global() -> None:
    gateway, ledger, user_ledger, provider = _gateway(user_limit=1)
    await _chat(gateway)
    assert provider.calls == 1
    assert await ledger.spent() == 1
    assert await user_ledger.spent("u_102") == 1

    with pytest.raises(BudgetExceeded) as excinfo:
        await _chat(gateway)
    assert "个人模型预算" in str(excinfo.value)
    # 被拒的调用没有真的花钱，也不该占着全局额度
    assert provider.calls == 1
    assert await ledger.spent() == 1
    assert await user_ledger.spent("u_102") == 1


async def test_user_budget_settles_actual_cost() -> None:
    gateway, ledger, user_ledger, _ = _gateway(user_limit=5)
    await _chat(gateway)
    await _chat(gateway)
    assert await ledger.spent() == 2
    assert await user_ledger.spent("u_102") == 2


async def test_user_budget_isolated_between_users() -> None:
    gateway, _, user_ledger, provider = _gateway(user_limit=1)
    await _chat(gateway, "u_1")
    with pytest.raises(BudgetExceeded):
        await _chat(gateway, "u_1")
    await _chat(gateway, "u_2")
    assert provider.calls == 2
    assert await user_ledger.spent("u_1") == 1
    assert await user_ledger.spent("u_2") == 1


async def test_user_limit_zero_means_unlimited_and_skips_ledger() -> None:
    budgets = _CountingUserLedger()
    gateway, _, _, provider = _gateway(user_limit=0, user_ledger=budgets)
    await _chat(gateway)
    # 不限制时不要多一次布隆/Redis 往返
    assert budgets.reserve_calls == 0
    assert provider.calls == 1


async def test_user_budget_released_when_provider_fails() -> None:
    gateway, ledger, user_ledger, _ = _gateway(user_limit=5, provider_result=ProviderError("boom"))
    with pytest.raises(ModelUnavailable):
        await _chat(gateway)
    assert await ledger.spent() == 0
    assert await user_ledger.spent("u_102") == 0


async def test_user_budget_not_enforced_without_policy() -> None:
    """最小部署可以不配个人预算：行为与 ADR-0013 的全局预算一致。"""
    ledger = InMemoryBudgetLedger(1000)
    provider = _FakeProvider(RawCompletion("ok", 100, 20))
    gateway = ModelGateway(
        [CLOUD],
        budget=ledger,
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: provider,
    )
    await _chat(gateway)
    assert provider.calls == 1
    assert await ledger.spent() == 1


async def test_gateway_uses_policy_default_limit() -> None:
    """生产装配用的是 `UserBudgetPolicy`：默认值要能直接挡住第二次调用。"""
    policy = UserBudgetPolicy(InMemoryUserBudgetStore(), default_cents=1, ttl_s=0)
    ledger = InMemoryUserBudgetLedger()
    provider = _FakeProvider(RawCompletion("ok", 100, 20))
    gateway = ModelGateway(
        [CLOUD],
        budget=InMemoryBudgetLedger(1000),
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: provider,
        user_budget=ledger,
        user_limits=policy,
    )
    await _chat(gateway)
    with pytest.raises(BudgetExceeded):
        await _chat(gateway)
    assert await ledger.spent("u_102") == 1
    assert provider.calls == 1


async def test_policy_zero_override_means_unlimited_for_that_user() -> None:
    """显式覆盖 0 = 该用户不限：默认值对他不再生效，也不用查个人账本。"""
    policy = UserBudgetPolicy(InMemoryUserBudgetStore(), default_cents=1, ttl_s=0)
    await policy.set_limit("u_102", 0, updated_by="admin_1")

    budgets = _CountingUserLedger()
    provider = _FakeProvider(RawCompletion("ok", 100, 20))
    gateway = ModelGateway(
        [CLOUD],
        budget=InMemoryBudgetLedger(1000),
        meter=InMemoryModelCallStore(),
        settings=_settings(),
        provider_factory=lambda route: provider,
        user_budget=budgets,
        user_limits=policy,
    )
    await _chat(gateway)
    await _chat(gateway)
    assert budgets.reserve_calls == 0
    assert provider.calls == 2
