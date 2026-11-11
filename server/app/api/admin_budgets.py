"""按用户日预算的读取与覆盖（ADR-0026）。

- 覆盖表只存「与默认值不同」的用户；没有行就继承 `ONCALL_USER_DAILY_BUDGET_CNY`
- `daily_cents = 0` 是显式的「该用户不限」；`DELETE` 才回到环境默认值
- 管理页读的是真实配置（`allow_stale=False`），不能拿旧快照冒充现状
- 今日用量读账本快照（ADR-0028）；Redis 故障返回 503，不拿内存账本冒充
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.budgets.observability import ReservationStats, summarize
from app.budgets.policy import UserBudgetPolicy, get_user_budget_policy
from app.budgets.store import UserBudgetOverride
from app.core.config import get_settings
from app.core.limits import (
    RESERVATION_STALE_S,
    BudgetLedger,
    LedgerUnavailable,
    UserBudgetLedger,
    budget_day,
    get_budget_ledger,
    get_user_budget_ledger,
)
from app.core.logging import get_logger
from app.schemas.budget import (
    BudgetUsageResponse,
    GlobalBudgetUsageOut,
    UserBudgetListResponse,
    UserBudgetOut,
    UserBudgetUpdateRequest,
    UserBudgetUsageOut,
)
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/budgets", tags=["admin-budgets"])
log = get_logger(__name__)

#: 用户 id 来自 token 的 `sub`（CLI 签发）；这里只挡住空串与空白，不改写
UserIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^\S{1,64}$")]


def _out(override: UserBudgetOverride) -> UserBudgetOut:
    return UserBudgetOut(
        user_id=override.user_id,
        daily_cents=override.daily_cents,
        updated_by=override.updated_by,
        updated_at=override.updated_at,
    )


class _StatsFields(TypedDict):
    reserved_cents: int
    reservation_count: int
    stale_count: int
    stale_cents: int
    oldest_age_s: float | None


def _stats_fields(stats: ReservationStats) -> _StatsFields:
    return {
        "reserved_cents": stats.reserved_cents,
        "reservation_count": stats.reservation_count,
        "stale_count": stats.stale_count,
        "stale_cents": stats.stale_cents,
        "oldest_age_s": stats.oldest_age_s,
    }


@router.get("")
async def list_budgets(
    policy: Annotated[UserBudgetPolicy, Depends(get_user_budget_policy)],
    _admin: Annotated[Identity, Depends(require_admin)],
) -> UserBudgetListResponse:
    try:
        overrides = await policy.overrides(allow_stale=False)
    except SQLAlchemyError as exc:
        log.error("user_budget_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "预算配置暂不可用") from exc
    return UserBudgetListResponse(
        default_cents=policy.default_cents,
        overrides=[_out(item) for _, item in sorted(overrides.items())],
    )


@router.get("/usage")
async def budget_usage(
    _admin: Annotated[Identity, Depends(require_admin)],
    ledger: Annotated[BudgetLedger, Depends(get_budget_ledger)],
    user_ledger: Annotated[UserBudgetLedger, Depends(get_user_budget_ledger)],
) -> BudgetUsageResponse:
    """今日账本快照（ADR-0028）：已用、未结算预扣与卡住的笔数。

    只读账本：不读覆盖表、不读 model_calls。前者的真相源是配置接口，
    后者的真相源是 `/admin/cost/summary`，三个口径不能互相替代。
    """
    try:
        global_snapshot = await ledger.snapshot()
        user_snapshots = await user_ledger.snapshot()
    except LedgerUnavailable as exc:
        log.error("budget_usage_read_failed", error=str(exc))
        raise ApiError(503, "LEDGER_UNAVAILABLE", "预算账本暂不可用，请稍后重试") from exc
    global_stats = summarize(global_snapshot, stale_after_s=RESERVATION_STALE_S)
    return BudgetUsageResponse(
        day=budget_day(),
        stale_after_s=RESERVATION_STALE_S,
        global_usage=GlobalBudgetUsageOut(
            limit_cents=get_settings().daily_budget_cents,
            spent_cents=global_snapshot.spent_cents,
            **_stats_fields(global_stats),
        ),
        users=[
            UserBudgetUsageOut(
                user_id=user_id,
                spent_cents=snapshot.spent_cents,
                **_stats_fields(summarize(snapshot, stale_after_s=RESERVATION_STALE_S)),
            )
            for user_id, snapshot in sorted(user_snapshots.items())
        ],
    )


@router.put("/{user_id}")
async def set_budget(
    user_id: UserIdPath,
    body: UserBudgetUpdateRequest,
    policy: Annotated[UserBudgetPolicy, Depends(get_user_budget_policy)],
    admin: Annotated[Identity, Depends(require_admin)],
) -> UserBudgetOut:
    try:
        await policy.set_limit(user_id, body.daily_cents, updated_by=admin.user_id)
        # 回读一次：PUT 的响应要能直接填进表格，`updated_at` 以库里的值为准
        overrides = await policy.overrides(force=True, allow_stale=False)
    except SQLAlchemyError as exc:
        log.error("user_budget_write_failed", user_id=user_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "预算配置保存失败，请稍后重试") from exc
    saved = overrides.get(user_id)
    if saved is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "预算配置保存后读回失败，请刷新重试")
    log.info(
        "user_budget_updated",
        user_id=user_id,
        daily_cents=saved.daily_cents,
        by=admin.user_id,
    )
    return _out(saved)


@router.delete("/{user_id}", status_code=204)
async def clear_budget(
    user_id: UserIdPath,
    policy: Annotated[UserBudgetPolicy, Depends(get_user_budget_policy)],
    admin: Annotated[Identity, Depends(require_admin)],
) -> Response:
    """删除覆盖，回到环境默认值。删除一个不存在的覆盖也算成功（幂等）。"""
    try:
        await policy.clear(user_id)
    except SQLAlchemyError as exc:
        log.error("user_budget_delete_failed", user_id=user_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "预算配置保存失败，请稍后重试") from exc
    log.info("user_budget_cleared", user_id=user_id, by=admin.user_id)
    return Response(status_code=204)
