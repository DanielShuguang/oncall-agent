# ADR-0110：恢复审计统计增加恢复置顶数

## 背景

ADR-0109 已为每条恢复审计记录 `repinned_count`，但审计页顶部统计卡仍只有恢复操作、用户、会话三个汇总。管理员看容量是否吃紧时，需要先逐行加总「恢复置顶」，无法直接判断窗口内恢复会话中有多少成功恢复了置顶。

## 备选方案

| 方案 | 优点 | 不采纳原因 |
|---|---|---|
| 前端按当前页求和 | 无后端改动 | 只是当前页，不是窗口汇总；翻页后会变 |
| 统计接口拉全量记录再求和 | 不改 SQL | 窗口可能很大，浪费带宽和内存 |
| 在统计查询里加 `sum(repinned_count)` | 一次查询、与其它汇总同口径 | 采纳 |

## 决策

1. `SessionRestoreAuditStats` 增加 `repinned`，为窗口内过滤后记录的 `repinned_count` 之和；与 `restores`/`users`/`sessions` 同一窗口。
2. 内存实现遍历已过滤 records 累加；PG 在汇总查询增加 `coalesce(sum(repinned_count), 0)`，不新增日趋势字段。
3. `SessionRestoreAuditStatsOut` 增加 `repinned: int = 0`，旧客户端可忽略。
4. 统计 CSV 的 `summary` 增加 `repinned` 行；响应头增加 `X-Export-Repinned`，与既有 `X-Export-*` 一致。
5. 前端统计卡增加「恢复置顶」第四项，仅显示总数，不做按日/按小时趋势。
6. 无迁移；`repinned` 不是独立审计表，仍以 `session_restore_audits.repinned_count` 为唯一事实源。

## 后果

- 旧审计行的 `repinned_count` 为 0，因此统计也按 0 计入；历史窗口无法区分「当时未置顶」和「容量不足」。
- `repinned` 只表示恢复了置顶的会话数，不能反推恢复总数；需要同时看 `sessions`。
- 新增字段是向后兼容的；旧前端忽略，不影响其它统计。
- 不做日趋势，避免把 `daily` 从两个指标扩成三个后再为每个日期补零。

## 验证

- 默认 `535 passed + 42 skipped`；PG-only `574 passed + 3 skipped`；PG+Redis `577 passed`。
- `ruff check` / `ruff format --check` 210 files / `mypy app` 119 files。
- 前端 29 files / 149 tests、lint 0/0、format 147、build 2944 modules。
- 用例：`test_admin_sessions.py::test_session_restore_audit_stats` 断言 7 天窗口旧记录 `repinned=0`、30 天窗口为 3；统计 CSV 断言 `repinned` summary 与 `X-Export-Repinned`。
- 存储契约：`_exercise_restore_pin` 按 `session_id` 过滤后断言 `repinned=1`，覆盖内存与 PG 的汇总路径；历史审计 fixture 的 `session_ids` 长度与 `restored_count` 对齐，不构造只在内存里成立的非法行。

## 待定

- 是否给 `daily` 增加恢复置顶趋势；
- 是否在统计卡标注「恢复置顶 / 恢复会话」比例；
- 容量不足时是否在统计卡提示「有会话恢复但未置顶」。
