# ADR-0095：导出审计按独立保留期清理

## 背景

ADR-0094 新增 `export_audits`，记录审批/恢复/置顶审计六个 CSV 导出端点的下载行为。
表本身只增不删；ADR-0094 明确把保留策略留作待定，README 与 docs/02 也写着
「当前不清理」。私有化部署里每次导出都会新增一行，长期运行后表会无限增长，
和事件、计量、恢复/置顶审计已有的保留机制不一致。

导出记录是治理证据，不属于用户正文；但也不需要永久保留。默认保留一年，覆盖
一次审计周期，之后和恢复/置顶审计一样按时间清理。

## 备选方案

| 方案 | 结论 |
|---|---|
| 不清理，靠管理员手工删 | 不采纳：没有入口，也没有可解释的保留语义 |
| 复用事件/正文 180 天 | 不采纳：导出审计不是 run 内容，事件清理只处理终态 run |
| 复用恢复/置顶审计 365 天 | 不采纳：三类审计的体量与合规要求不同，独立配置才能按现场调整 |
| **独立 `ONCALL_EXPORT_AUDIT_RETENTION_DAYS`（默认 365）** | **采纳**：与 ADR-0083 同模式，不动表结构 |

## 决策

1. 新增 `ONCALL_EXPORT_AUDIT_RETENTION_DAYS`，默认 `365`；启动期校验 `>= 1`，
   配 0 直接拒绝。
2. `RunStore.prune_export_audits(*, created_before, limit=200, dry_run=False)`：
   内存与 Postgres 都按 `(created_at, id)` 取一批，只删严格早于阈值的行；
   dry-run 只返回候选数。
3. `RetentionSweeper` 使用独立阈值，顺序为「… → 置顶审计 → 导出审计 → 计量」；
   `RetentionResult` 增加 `export_audits_before` / `export_audits`，CLI 与后台日志
   同步输出。
4. 清理是幂等、分批的：`limit` 与 `retention_max_batches` 复用现有批大小；
   取不满一批即停，达到上限标 `capped`。
5. 不做冷归档、不做按用户删除、不做导出文件回放；删除只发生在保留期之后。
6. 本次不改表结构，迁移仍停在 `0023`。

## 后果

- 导出审计默认最多保留一年；需要更久时调大环境变量，重启后生效。
- 删除后无法再查该次导出的 who/resource/filters/row_count；这是有意的保留边界。
- 清理任务只按时间删，不区分资源类型；无法单独保留某一类导出记录。
- dry-run 只预览第一批，不写库；与事件/计量清理口径一致。

## 验证

- `server/tests/test_config.py`：拒绝 0，默认 365。
- `server/tests/test_retention.py`：导出审计按自己的阈值清理，dry-run 不删；
  `test_sweep_cutoffs_follow_settings` 断言 365 天阈值。
- `server/tests/test_store_contract.py`：内存/PG 的 dry-run、批量删除、删后列表为空。
- 默认 **526 passed + 40 skipped**、PG-only **563 passed + 3 skipped**、
  PG+Redis **566 passed**；`ruff check` / `ruff format --check` 205 files /
  `mypy app` 119 files。
- 前端未改，沿用 27 files / 130 tests。

## 待定

- 是否需要按资源类型设置不同保留期（例如审批导出比统计导出留更久）。
- 是否提供导出审计的冷归档/对象存储。
- 单条审计详情与「再次导出」；ADR-0094 已明确暂不做。
