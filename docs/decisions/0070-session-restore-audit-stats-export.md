# ADR-0070：会话恢复审计统计 CSV 导出

- 状态：已采纳
- 日期：2026-11-15
- 相关：ADR-0065（统计接口）、ADR-0066（统计过滤）、ADR-0067（日期范围）、
  ADR-0062（审计列表导出）、ADR-0068（审批统计导出）

## 背景

会话恢复审计管理页已经有全局/过滤后的统计卡：近 7/30/90 天或自定义 UTC
日期范围内的恢复操作数、涉及用户数、恢复会话数与稀疏日趋势（ADR-0065/0066/0067）。

但这些数字只能看，不能带走。交接、周报、容量评估和事故复盘需要一份可离线保存的
快照；逐条审计 CSV（ADR-0062）只包含单次恢复操作，无法复原统计窗口的汇总与日趋势。
审批统计已经用同一种「长表 CSV」解决过同类问题（ADR-0068），审计统计可以复用同一
形状与安全处理。

## 备选方案

| 方案 | 否决原因 |
|---|---|
| 前端遍历已加载审计行聚合 | 只覆盖已加载页，不是全量统计，且与后端统计口径可能漂移 |
| 复用逐条审计 CSV，让使用者自己算 | 无法恢复去重用户数、`restored_count` 汇总与稀疏日趋势；交接成本高 |
| JSON 导出 | 表格工具直接打开不友好，仍需二次转换 |
| 新增 `/stats/export` 之外的通用导出框架 | 当前只有审计统计一个调用方，抽象没有收益 |
| 异步导出/对象存储 | 统计行数最多 365×2+6，同步生成即可 |
| 引入 XLSX 多工作表 | 需要新依赖，且 CSV 已能覆盖当前场景 |

## 决策

1. **新增 `GET /admin/session-restores/stats/export`**：参数与统计接口一致
   （`days` 可选、`restored_from`/`restored_to`、`user_id`、`session_id`），
   仅管理员可调用；不接收 `cursor`/`limit`。
2. **窗口解析与统计接口共用**：抽出 `_stats_window(days, from, to)`，保证
   `days` 与日期范围二选一、窗口边界和 `days_out` 与 `/stats` 完全一致。
3. **CSV 用长表 `section,key,day,value`**：
   - `meta`：`days`、`since`、`until`；
   - `summary`：`restores`、`users`、`sessions`；
   - `daily`：每个有恢复记录的 UTC 自然日两行，`key=restores` / `key=sessions`。
   这样新增指标不需要改列结构；`day` 只用于 daily 行，其他行留空。
4. **同步导出，不截断**：日趋势最多 365 个日期、每天最多两行，总量有界；
   响应头 `X-Export-Days`、`X-Export-Restores`、`X-Export-Users`、
   `X-Export-Sessions` 让前端不解析 CSV 也能提示结果。
5. **复用 `csv_document`**：UTF-8 BOM、CRLF、ISO 8601 时间与公式注入防护与
   审批/审计导出保持一致；文件名 `session-restore-stats-{days}d-{UTC}.csv`，
   `Cache-Control: no-store`。
6. **前端按钮跟随当前统计窗口**：「导出统计」使用当前 `statsDays` 与已应用过滤；
   有自定义日期范围时不发 `days`。切换窗口/过滤立即失效在途导出并清提示，避免
   旧窗口的结果覆盖新状态。
7. **旧后端降级**：旧实例没有该端点时请求返回 404，前端在统计卡内显示错误，
   不影响列表/统计加载；不做版本探测。

## 后果

- 交接/周报可以直接带走一份与页面同口径的统计快照，不需要手工抄数字。
- CSV 是长表，直接透视前需要按 `section` 过滤；这是为了保持列稳定、避免每加一个
  指标就改表头。
- 统计与导出是两次独立查询，导出结果与页面上的数字可能相差一条新恢复操作；
  与 ADR-0057/0065 的「非同一快照」取舍一致。
- 不做下载审计（谁在何时导出了什么），也不做 XLSX/异步任务；这些仍在待定。
- 无迁移、无新索引；复用 `idx_session_restore_audits_time` 与现有过滤条件。

## 验证

- 后端新增 `test_export_session_restore_audit_stats_csv`：CSV 表头、BOM/CRLF、
  `meta`/`summary`/`daily` 行、`X-Export-*` 响应头、按 `user_id` 过滤后的汇总。
- 403/503 用例覆盖 `/stats/export`。
- 默认 `pytest`：**504 passed + 40 skipped**；PostgreSQL **541 passed + 3 skipped**；
  PostgreSQL + Redis **544 passed**。
- `ruff check` / `ruff format --check`（196 files）/ `mypy app`（114 files）通过。
- 前端：**89 tests / 18 files**、tsc、oxlint 0/0（73 files）、`oxfmt --check`
  81 files、`pnpm build` 通过。

## 待定

- 下载审计（谁在何时导出了哪些过滤条件/窗口）；
- XLSX 多工作表或列裁剪；
- 统计与导出共用同一数据库快照；
- 统计结果缓存/物化；
- 自定义日期范围的快捷预设（ADR-0067 待定）。
