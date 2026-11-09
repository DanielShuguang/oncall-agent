"""孤儿 run 回收（W6 后加固，ADR-0017）。

进程重启、被 kill 或容器被驱逐时，正在跑的 run 不会再有事件写入，`runs.status`
会永远停在 `running`：列表一直显示"执行中"，回放页等不到终态，失败率也统计不到。

这里只做一件事：把「超过阈值仍没有任何事件」的 running run 收敛为
`run.failed(RUN_INTERRUPTED)`，让前端、回放和看板都拿到终态。

**不自动重放写工具**：审批通过后的恢复执行如果崩在工具调用之后，无法判断工单
是否已经创建；自动重试可能重复开单（R10）。回收只收敛状态，工单由人工按
run_id 对账后重新发起。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.store import RunStore
from app.schemas.failure import FailureCategory

log = get_logger(__name__)

ERROR_CODE = "RUN_INTERRUPTED"


@dataclass(frozen=True)
class ReapResult:
    """一次回收的结果；`dry_run` 时 `reaped` 是"将被回收"的候选。"""

    older_than: datetime
    scanned: int
    reaped: list[str] = field(default_factory=list)
    dry_run: bool = False


def interrupted_payload(stale_min: int) -> dict[str, Any]:
    """`run.failed` 的 payload；口径见 ADR-0017。"""
    return {
        "error_code": ERROR_CODE,
        "message": (
            f"运行已超过 {stale_min} 分钟没有任何事件，判定为进程中断；"
            "为避免重复写操作不会自动重试，请人工确认后重新发起"
        ),
        "at_step": 0,
        "category": FailureCategory.INTERNAL.value,
    }


class RunRecovery:
    def __init__(self, store: RunStore, *, settings: Settings | None = None) -> None:
        self._store = store
        self._settings = settings or get_settings()

    async def reap(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
        dry_run: bool = False,
    ) -> ReapResult:
        at = now or datetime.now(UTC)
        older_than = at - timedelta(minutes=self._settings.stale_run_min)
        candidates = await self._store.list_stale_runs(older_than=older_than, limit=limit)
        payload = interrupted_payload(self._settings.stale_run_min)

        reaped: list[str] = []
        for candidate in candidates:
            if dry_run:
                reaped.append(candidate.run_id)
                continue
            # 候选列表与真正写入之间可能有人补了事件/结束了 run；
            # fail_stale_run 在事务内重新检查，返回 False 表示已不该回收
            if await self._store.fail_stale_run(
                candidate.run_id, older_than=older_than, payload=payload
            ):
                reaped.append(candidate.run_id)

        if reaped:
            log.warning(
                "stale_runs_reaped",
                count=len(reaped),
                dry_run=dry_run,
                older_than=older_than.isoformat(),
            )
        return ReapResult(
            older_than=older_than,
            scanned=len(candidates),
            reaped=reaped,
            dry_run=dry_run,
        )


__all__ = ["ERROR_CODE", "ReapResult", "RunRecovery", "interrupted_payload"]
