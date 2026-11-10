"""数据保留清理（ADR-0021）。

docs/02 §4 定义了保留期，但之前只有配置项、没有执行者：`run_events` 与
`model_calls` 只增不删，私有化部署里"数据不出内网"之外还必须回答"数据留多久"。

这里只做**执行**，策略写在 docs/02 §4 与 ADR-0021：

- 事件按 **run 整场**删除：只结束、且结束时间早于 `ONCALL_EVENT_RETENTION_DAYS`
  的 run 才会被清理；删除事件与写 `runs.events_pruned_at` 同事务。
  不做"逐条按事件时间删"——回放会从中间开始，前端拿不到 run.started。
- 计量按 `model_calls.created_at` 删除，保留 `runs` 上的汇总列。
- 不删 `runs`：运行列表、成本口径、多轮上下文（ADR-0020）都依赖它；
  run 级保留策略属于另一件事，见 ADR 待定段。

清理是幂等的：`events_pruned_at` 一旦写入，这场 run 不会再被选中；
dry-run 只列候选，不写任何东西。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.config import Settings, get_settings
from app.core.store import RunStore
from app.gateway.meter import ModelCallStore


@dataclass(frozen=True)
class RetentionResult:
    """一次清理的结果；`dry_run` 时两个计数都是"将处理"的候选。"""

    events_before: datetime
    calls_before: datetime
    run_ids: list[str] = field(default_factory=list)
    events: int = 0
    calls: int = 0
    dry_run: bool = False


class RetentionSweeper:
    def __init__(
        self,
        store: RunStore,
        calls: ModelCallStore,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._calls = calls
        self._settings = settings or get_settings()

    async def sweep(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> RetentionResult:
        if limit is not None and limit < 1:
            raise ValueError("limit 必须 >= 1")
        at = now or datetime.now(UTC)
        batch = limit if limit is not None else self._settings.retention_batch
        events_before = at - timedelta(days=self._settings.event_retention_days)
        calls_before = at - timedelta(days=self._settings.model_call_retention_days)

        pruned = await self._store.prune_events(
            finished_before=events_before, limit=batch, dry_run=dry_run
        )
        pruned_calls = await self._calls.prune_calls(
            created_before=calls_before, limit=batch, dry_run=dry_run
        )
        return RetentionResult(
            events_before=events_before,
            calls_before=calls_before,
            run_ids=pruned.run_ids,
            events=pruned.deleted,
            calls=pruned_calls,
            dry_run=dry_run,
        )


__all__ = ["RetentionResult", "RetentionSweeper"]
