# ADR-0129：工具配置变更历史保留清理

- 状态：已采纳
- 日期：2026-11-24
- 相关：[ADR-0037](0037-tool-setting-history.md)、[ADR-0021](0021-data-retention.md)、[ADR-0095](0095-export-audit-retention.md)
- 迁移：无（沿用 `0015` 的 `tool_setting_changes`）

## 背景

`tool_setting_changes` 是工具治理的追加式审计：每次真正变化的 PATCH 或权限矩阵保存都会写一行，
`before`/`after` 保存完整覆盖快照。它此前被定义为「长期保留」，不随 run 事件、正文、审批快照或
`export_audits` 清理；管理 API 使用越久，表越大，`GET /admin/tools/{name}/history` 与全表备份都会变慢。

ADR-0037 把「保留期/冷归档」列为待定；ADR-0021 的 `RetentionSweeper` 已按数据类别分别清理，
`export_audits`（ADR-0095）也已有独立 365 天保留期。工具历史同样需要一条明确的保留边界。

## 备选方案

| 方案 | 结论 |
|---|---|
| 永久保留，只加索引/归档 | 不采纳：表随管理操作无限增长，私有化现场没有运维入口 |
| 复用 `ONCALL_EXPORT_AUDIT_RETENTION_DAYS` | 不采纳：导出审计与工具配置审计的合规节奏不同，强行共用会让一个配置改两类数据 |
| 复用事件/正文保留期 | 不采纳：工具历史不属于 run 内容，不应被 run 保留策略牵连 |
| 独立保留期 + `RetentionSweeper` | 采纳：与其他审计一致，按 `changed_at` 独立清理 |
| 软删除/冷归档 | 暂不做：先给默认边界，确认真实归档需求后再设计 |

## 决策

1. 新增 `ONCALL_TOOL_HISTORY_RETENTION_DAYS`，默认 `365`，必须 `>= 1`；启动时校验。
2. `ToolSettingStore.prune_history(changed_before, limit=200, dry_run=False)` 按
   `(changed_at, id)` 升序取一批再删除；`dry_run` 只计数，不删行。
3. `RetentionSweeper` 使用自己的 cutoff：`now - tool_history_retention_days`；
   顺序为「… → 导出审计 → 工具历史 → 计量」。清理是幂等的，多副本同时跑不会重复计数。
4. `RetentionResult` 增加 `tool_history_before` 与 `tool_history`；CLI `prune` JSON 与后台
   `retention_pruned` 日志同步暴露这两个字段。
5. 删除按 `changed_at` 而不是按工具：一个工具的历史可能跨越多个保留窗口，逐工具删会让历史出现
   无法解释的缺口，按时间删是唯一可解释的边界。
6. 不加迁移、不归档、不做软删除；超过保留期的历史不可恢复。历史是审计，不是回滚存储；
   需要回滚的变更应在保留期内完成。

## 后果

- 超过保留期的历史行被物理删除，`GET /admin/tools/{name}/history`、回滚、CSV 导出都不再返回它们；
  与事件/恢复审计一致，删除不可逆。
- 升级后第一次清理可能一次性删除大量旧行；`dry-run` 先看候选，生产和测试都应先跑。
- 不在默认路径上做「按工具保留」：如果现场确实需要不同工具的保留期，后续再加覆盖表；当前
  不引入新表。
- 恢复/回滚的引用只指向保留期内的记录；被清理的历史不能再回滚，符合「审计证据」而不是
  「配置版本库」的定位。
- 清理失败不会阻塞其他类别；`RetentionSweeper` 对单类失败记日志并继续，下一轮重试。

## 验证

- `server/tests/test_retention.py::test_prunes_tool_history_by_own_retention`：内存 store 在
  366 天后 dry-run 计数 1 但不删除，实跑删除 1，再跑 0。
- `server/tests/test_tool_history_pg.py::test_prunes_history_before_cutoff`：PG 两条历史，
  dry-run=2、实删=2、再跑=0。
- 默认 `pytest`：**538 passed + 42 skipped**；PG-only **577 passed + 3 skipped**；
  PG+Redis **580 passed**（本次未改变测试函数数）。
- `ruff check` / `ruff format --check` 210 files / `mypy app` 119 files 通过。
- 前端未改，沿用 36 files / 183 tests、build 2954。

## 待定

- 冷归档到对象存储（当前直接删除）。
- 按工具/来源设置不同保留期（当前一个全局值）。
- 管理页提示「历史已按保留期清理」的只读标记。

