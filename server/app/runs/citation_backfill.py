"""历史 run 的引用快照回填（ADR-0042）。

ADR-0031 上线时只对之后写入的 `message.completed` 投影 `runs.citations`，
更早的 run 即使事件还在也没有快照，历史侧栏不出角标。这个模块提供一次性、
可重复执行的运维回填：从仍存在的事件里重建快照，不改事件、不改保留语义。

只处理同时满足以下条件的 run：

- `citations` 仍为空；
- 正文未清理（`content_pruned_at is None`）：正文清理时快照按 ADR-0023 一并清空，
  回填会把「只剩摘要」的 run 又长出引用片段；
- 事件未清理（`events_pruned_at is None`）：没有 `message.completed` 就无从重建；
- 有回答正文（`output is not None`）：只有摘要的 run 不再回填。

事件已被保留策略清掉的 run 不报错、不计数到 `filled`，只计入
`skipped_no_citations`。写回时 `set_citations` 是条件写入，已经回填或并发写入
的 run 不会被覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.store import RunStore, _citation_snapshot
from app.schemas.event import EventType, RunEvent

#: 单次回填默认扫描多少场 run；CLI 的 `--limit` 可覆盖
DEFAULT_BACKFILL_LIMIT = 100


@dataclass(frozen=True)
class CitationBackfillResult:
    """一次回填的结果。

    `scanned` 是候选（仍无快照、正文与事件都还在）的 run 数；`filled` 是真正写入
    快照的 run 数（dry-run 时是**可写**数）；`skipped_no_citations` 是候选里
    没有可重建引用的 run 数（事件里没有 `message.completed`，或该事件的
    citations 为空/不可用）。并发写入导致 `set_citations` 返回 False 的 run
    不在 `filled` 里，也不计入 `skipped_no_citations`——这是运维动作，
    不做重试，下一轮再扫描即可。
    """

    scanned: int
    filled: int
    skipped_no_citations: int
    dry_run: bool


def _last_citations(events: list[RunEvent]) -> list[dict[str, Any]] | None:
    """取最后一条 `message.completed` 的引用快照；没有就返回 None。"""
    for event in reversed(events):
        if event.type is EventType.MESSAGE_COMPLETED:
            return _citation_snapshot(event.payload.get("citations"))
    return None


async def backfill_citations(
    store: RunStore,
    *,
    limit: int = DEFAULT_BACKFILL_LIMIT,
    dry_run: bool = False,
) -> CitationBackfillResult:
    """为最多 `limit` 场历史 run 回填引用快照（ADR-0042）。

    `dry_run=True` 只统计可回填的 run，不写库。重复执行是安全的：写过快照的
    run 不再进入候选。
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    records = await store.list_runs_without_citations(limit=limit)
    if not records:
        return CitationBackfillResult(scanned=0, filled=0, skipped_no_citations=0, dry_run=dry_run)

    events_by_run = await store.events_for_runs([record.run_id for record in records])
    filled = 0
    skipped = 0
    for record in records:
        citations = _last_citations(events_by_run.get(record.run_id, []))
        if not citations:
            skipped += 1
            continue
        if not dry_run and not await store.set_citations(record.run_id, citations):
            # 已经被并发写入（或 run 刚被删除）——下一轮再看，不当成失败
            continue
        filled += 1

    return CitationBackfillResult(
        scanned=len(records),
        filled=filled,
        skipped_no_citations=skipped,
        dry_run=dry_run,
    )
