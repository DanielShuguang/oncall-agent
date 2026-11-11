"""预算账本的只读汇总（ADR-0028）。

账本快照包含「已花 + 未结算预扣」；管理页要回答的问题不是逐笔明细，
而是「有没有预扣卡住」。这里只做纯计算，不碰 Redis / DB。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.limits import LedgerSnapshot


@dataclass(frozen=True, slots=True)
class ReservationStats:
    reserved_cents: int
    reservation_count: int
    stale_count: int
    stale_cents: int
    #: 最老一笔预扣的年龄；没有预扣或全部是没有时间戳的旧格式时为 None
    oldest_age_s: float | None


def summarize(snapshot: LedgerSnapshot, *, stale_after_s: float) -> ReservationStats:
    """把快照压成管理页需要的统计。

    旧格式预扣（`age_s is None`）不计入 stale：时间不可知时宁可少报，
    也不要每天固定报警一批历史数据。
    """
    stale = [
        item
        for item in snapshot.reservations
        if item.age_s is not None and item.age_s >= stale_after_s
    ]
    ages = [item.age_s for item in snapshot.reservations if item.age_s is not None]
    return ReservationStats(
        reserved_cents=sum(item.cents for item in snapshot.reservations),
        reservation_count=len(snapshot.reservations),
        stale_count=len(stale),
        stale_cents=sum(item.cents for item in stale),
        oldest_age_s=round(max(ages), 1) if ages else None,
    )
