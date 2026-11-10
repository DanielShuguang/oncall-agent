"""数据保留清理（ADR-0021 / ADR-0023）。

docs/02 §4 定义了保留期，但之前只有配置项、没有执行者：`run_events` 与
`model_calls` 只增不删，私有化部署里"数据不出内网"之外还必须回答"数据留多久"。
`runs.input/output` 这两列产品正文同理——按权限回收（ADR-0022）解决"谁能看"，
不解决"留多久"。

这里只做**执行**，策略写在 docs/02 §4、ADR-0021 与 ADR-0023：

- 事件按 **run 整场**删除：只结束、且结束时间早于 `ONCALL_EVENT_RETENTION_DAYS`
  的 run 才会被清理；删除事件与写 `runs.events_pruned_at` 同事务。
  不做"逐条按事件时间删"——回放会从中间开始，前端拿不到 run.started。
- 计量按 `model_calls.created_at` 删除，保留 `runs` 上的汇总列。
- 正文（`runs.input/output`）按 `ONCALL_RUN_CONTENT_RETENTION_DAYS` 清空，
  写 `runs.content_pruned_at`，只留运行摘要。配置层强制正文保留期不短于事件
  保留期：事件里是同一段回答正文，先清 runs 等于没清。
- 不删 `runs` 行：运行列表、成本口径、失败率都依赖它；多轮上下文按 `output`
  是否为空自然跳过已清空的历史轮次。

步骤顺序是「事件 → 正文 → 计量」：同一轮里先删事件再清正文，正文不会比
事件活得更久（多副本下也只在同一批次内先后）。

清理是幂等的：`events_pruned_at` / `content_pruned_at` 一旦写入，这场 run 不会
再被选中；dry-run 只预览第一批候选，不写任何东西（不写标记时循环会把同一批
重复计数）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.config import Settings, get_settings
from app.core.store import RunStore
from app.gateway.meter import ModelCallStore


@dataclass(frozen=True)
class RetentionResult:
    """一次清理的结果；`dry_run` 时计数是"将处理"的候选（只预览第一批）。"""

    events_before: datetime
    calls_before: datetime
    content_before: datetime
    run_ids: list[str] = field(default_factory=list)
    events: int = 0
    calls: int = 0
    #: 正文被清空的 run（dry-run 时是候选场次；清理按场计，不按行计）
    content_run_ids: list[str] = field(default_factory=list)
    #: 本轮的批大小，用来解释 `capped` 与吞吐
    batch: int = 0
    #: 跑到批次上限时仍有候选（`dry_run` 表示预览被截断）；积压可能还没清完
    capped: bool = False
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
        max_batches: int | None = None,
        dry_run: bool = False,
    ) -> RetentionResult:
        if limit is not None and limit < 1:
            raise ValueError("limit 必须 >= 1")
        if max_batches is not None and max_batches < 1:
            raise ValueError("max_batches 必须 >= 1")
        at = now or datetime.now(UTC)
        batch = limit if limit is not None else self._settings.retention_batch
        rounds = max_batches if max_batches is not None else self._settings.retention_max_batches
        if dry_run:
            # dry-run 不写标记，循环只会把同一批候选反复计数；预览到此为止
            rounds = min(rounds, 1)
        events_before = at - timedelta(days=self._settings.event_retention_days)
        calls_before = at - timedelta(days=self._settings.model_call_retention_days)
        content_before = at - timedelta(days=self._settings.run_content_retention_days)

        run_ids: list[str] = []
        content_run_ids: list[str] = []
        events = 0
        calls = 0
        capped = False
        for _ in range(rounds):
            pruned = await self._store.prune_events(
                finished_before=events_before, limit=batch, dry_run=dry_run
            )
            # 正文在事件之后清：事件里带着同一段回答正文，先清 runs 等于没清
            pruned_content = await self._store.prune_contents(
                finished_before=content_before, limit=batch, dry_run=dry_run
            )
            pruned_calls = await self._calls.prune_calls(
                created_before=calls_before, limit=batch, dry_run=dry_run
            )
            run_ids.extend(pruned.run_ids)
            content_run_ids.extend(pruned_content.run_ids)
            events += pruned.deleted
            calls += pruned_calls
            # 都取不满一批才收手：只满足一部分时继续排空其余；达到批次上限
            # 则留给下一轮，保证单次扫描的锁与事务量有上界
            if (
                len(pruned.run_ids) < batch
                and len(pruned_content.run_ids) < batch
                and pruned_calls < batch
            ):
                break
        else:
            # 跑满上限说明可能还有积压：调用方要记 warning，别把「本轮清完」当默认
            capped = True

        return RetentionResult(
            events_before=events_before,
            calls_before=calls_before,
            content_before=content_before,
            run_ids=run_ids,
            events=events,
            calls=calls,
            content_run_ids=content_run_ids,
            batch=batch,
            capped=capped,
            dry_run=dry_run,
        )


__all__ = ["RetentionResult", "RetentionSweeper"]
