# ADR-0083：会话置顶审计接入保留清理

- 状态：已采纳
- 日期：2026-11-16
- 相关：ADR-0021（数据保留清理）、ADR-0059（会话恢复审计）、
  ADR-0081（置顶审计）、ADR-0082（置顶审计分页）

## 背景

会话置顶/取消置顶审计（ADR-0081）用于回答「谁在何时置顶或取消」，是治理证据，
不是会话内容。该表只增不删，ADR-0081 已把「是否接入 RetentionSweeper」列为待定。

治理审计也需要有回收边界：默认无限保留会让表随时间单调增长，且 `GET
/admin/session-pins` 的游标只能翻到更早的记录，无法解决存储成本。但置顶审计的
保留语义与事件/正文不同——不能因为内容保留期调短就顺带删掉审计，也不能复用
恢复审计的保留期（两类操作的价值与频率不同）。

## 备选方案

| 方案 | 否决原因 |
|---|---|
| 不清理，永久保留 | 表单调增长；与 ADR-0021 的「保留清理」体系不一致 |
| 复用事件/正文保留期 | 审计是治理证据，不应随内容保留期缩短而丢失 |
| 复用恢复审计保留期 | 两类操作频率与审计价值不同，耦合后无法独立调参 |
| 数据库 TTL / 分区表 | 当前 PostgreSQL 版本与部署复杂度不值当；没有按行 TTL |
| 清理时保留最近 N 条而非按时间 | 管理员无法解释「为什么这条 300 天还在、那条 400 天没了」 |
| 异步后台单独任务 | 现有 `RetentionSweeper` 已有批次/上限/日志/dry-run，复用成本最低 |

## 决策

1. **独立保留期**：新增 `ONCALL_SESSION_PIN_AUDIT_RETENTION_DAYS`，默认 **365 天**；
   启动时校验 `>= 1`。与事件/正文/模型计量/恢复审计的保留期互不影响。
2. **按 `created_at` 清理**：审计行没有 `resolved_at` 概念，操作时间即 `created_at`；
   清理阈值 `now - retention_days`，严格早于阈值才删。
3. **接入 `RetentionSweeper`**：在「恢复审计 → 置顶审计 → 计量」链路中追加一步，
   每轮每批最多 `ONCALL_RETENTION_BATCH`（默认 200）行；所有子步骤都取不满一批
   才停止本轮，跑满 `ONCALL_RETENTION_MAX_BATCHES` 仍计 `retention_backlog_remaining`。
4. **存储接口**：`prune_session_pin_audits(*, created_before, limit=200, dry_run=False)
   -> int`。内存按 `(created_at, audit_id)` 排序后取前 `limit`；PG 用
   `created_at < before ORDER BY created_at, id LIMIT`，实跑在单事务内删除；
   `dry_run` 只返回候选数，不删除。
5. **可观测性**：`RetentionResult` 增加 `session_pin_audits_before` 与
   `session_pin_audits`；`prune` CLI JSON 与后台日志同步输出，便于先 dry-run
   看候选、再决定是否实跑。
6. **无迁移**：表结构不变，只增加清理逻辑；迁移仍到 `0022`。置顶审计仍然只记
   显式 `pin`/`unpin`，隐藏/恢复导致的置顶清理不写。
7. **不做**：不做前端管理页、导出、按会话/用户单独保留期；保留期只做全局配置。

## 后果

- `session_pin_audits` 不再无限增长；默认一年后由后台清理，现场可通过环境变量
  调长或调短。
- 清理是**不可逆**的；需要长期留档时应在到期前导出（当前无导出，属于待定）。
- 清理与 `GET /admin/session-pins` 分页互不影响；已删除的审计不会再出现在游标
  后续页，翻页期间可能出现「跳页」——与 ADR-0082 的「无稳定快照」一致。
- 置顶审计的保留期独立于恢复审计；两类审计可以分别按 365 天/更长保留，不会
  因为一个配置影响另一个。
- 清理失败不会让后台任务崩溃：`RetentionSweeper` 捕获异常并记
  `retention_sweep_failed`，下一轮重试。

## 验证

- `test_prunes_session_pin_audits_by_own_retention`：pin 一次 → `sweep(now+366d)`
  dry-run 计数 1 且审计仍在 → 实跑删 1 → 再跑 0。
- `test_sweep_cutoffs_follow_settings`：默认阈值 `now - 365d`。
- `test_store_contract.py`：总审计 >=5；`created_before=now+1d, limit=3`
  dry-run 返回 3 且列表不变，实跑返回 3 且列表少 3；内存/PG 同一契约。
- `test_config.py`：`session_pin_audit_retention_days=0` 启动拒绝，默认 365。
- 实跑：默认 512+40、PG 549+3、Redis 552；ruff 200 files / mypy 116 files；
  前端未改 114/24。迁移 `0022` 往返仍通过（无新迁移）。

## 待定

- 是否提供审计导出（已由 [ADR-0084](0084-session-pin-audit-export.md) 以
  同步 CSV、最多 5000 行补上，便于保留期前留档）。
- 是否支持按租户/用户覆盖保留期；当前只有全局环境变量。
- 清理与分页并发的「翻页期间跳页」是否需要在 UI 提示；当前无前端页面。
- 是否把置顶审计接入下载审计/前端管理页，与恢复审计共用治理视图。
