"""成本汇总接口（W4 D19）。

口径：直接聚合 `model_calls`，不维护独立汇总表 —— 计量行是唯一数据源，
看板与 `runs` 的 token/cost 必须对得上（一致性测试见 tests/test_metrics_pg.py）。
日期按 UTC 自然日解释（R6），`to` 为闭区间。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.gateway.meter import CostSummary, GroupBy, ModelCallStore, get_model_call_store
from app.schemas.cost import CostItemOut, CostSummaryResponse
from app.tools.registry import Identity

router = APIRouter(prefix="/admin/cost", tags=["admin-cost"])

MAX_RANGE_DAYS = 366


@router.get("/summary")
async def cost_summary(
    _admin: Annotated[Identity, Depends(require_admin)],
    store: Annotated[ModelCallStore, Depends(get_model_call_store)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    group_by: Annotated[GroupBy, Query()] = "day",
) -> CostSummaryResponse:
    start_date = from_ or (datetime.now(UTC).date() - timedelta(days=6))
    end_date = to or datetime.now(UTC).date()
    if start_date > end_date:
        raise ApiError(422, "INVALID_RANGE", "from 不能晚于 to")
    if (end_date - start_date).days > MAX_RANGE_DAYS:
        raise ApiError(422, "INVALID_RANGE", f"查询范围不能超过 {MAX_RANGE_DAYS} 天")

    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    try:
        summary = await store.summary(start=start, end=end, group_by=group_by)
    except SQLAlchemyError as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
    return _response(summary)


def _response(summary: CostSummary) -> CostSummaryResponse:
    return CostSummaryResponse(
        total_cents=summary.total_cents,
        calls=summary.calls,
        items=[
            CostItemOut(
                key=item.key,
                calls=item.calls,
                token_in=item.token_in,
                token_out=item.token_out,
                cost_cents=item.cost_cents,
            )
            for item in summary.items
        ],
    )
