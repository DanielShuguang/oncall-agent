# ADR-0090：置顶审计统计 CSV 导出

- 状态：已采纳
- 日期：2026-11-17
- 相关：ADR-0070（恢复审计统计导出）、ADR-0084（置顶审计列表导出）、ADR-0087（置顶审计统计）、ADR-0089（统计跟随过滤）

## 背景

置顶审计管理页已经能按用户/会话/动作/日期范围筛选，并在统计卡展示
`pins`/`unpins`/`users`/`sessions` 与 UTC 稀疏日趋势（ADR-0087/0089）。
但统计数字只能看、不能带走：管理员做周报或对账时仍要手工抄数，和恢复审计
统计已有 CSV 导出（ADR-0070）不对称。

列表导出（ADR-0084）导出的是审计明细，不是窗口汇总；两者的行数、字段与用途
都不同，不能复用同一个端点。这个缺口在 ADR-0089 的「待定」里已经记录：
「统计 CSV 另见 ADR-0070 的恢复审计，置顶审计暂不做」。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 前端把 `/stats` JSON 拼成 CSV | 不改后端，但 BOM/CRLF/公式注入/时间格式会在前端出现第二套实现；下载文件无法自证窗口 |
| 复用列表 `/export` | 行语义不同；列表只有明细，没有汇总与日趋势 |
| 新增 `/stats/export`，复用长表 | 与审批统计、恢复审计统计同一格式；窗口/过滤解析共享，前端只多一个按钮 | 
| 异步任务生成 | 统计最多 365 天、每日两行，输出有界；引入任务表/轮询没有收益 |

## 决策

1. **新增 `GET /admin/session-pins/stats/export`**，参数与 `/stats` 完全一致：
   `days` 1–365 可选、`created_from`/`created_to`、`user_id`/`session_id`/`action`。
   `days` 与日期范围二选一，窗口解析复用 `_stats_window`；不接收 `cursor`/`limit`。
2. **同步导出，不截断**：统计规模由窗口（最多 365 天）与每日两行界定，输出最多
   730 个 `daily` 行 + 固定 `meta`/`summary` 行；不设 5000 行列表上限。
3. **CSV 为长表** `section,key,day,value`，与 ADR-0070 一致：
   - `meta`：`days`/`since`/`until`；带过滤时追加 `user_id`/`session_id`/`action`；
   - `summary`：`pins`/`unpins`/`users`/`sessions`；
   - `daily`：每个有活动的 UTC 日期分别写 `pins` 与 `unpins` 两行。
   这样下载文件能自证统计口径，不依赖页面当前状态。
4. **格式复用 `csv_document`**：UTF-8 BOM、CRLF、ISO 8601 时间、公式注入字符
   前置单引号；文件名 `session-pin-stats-{days}d-{UTC}.csv`，`Cache-Control: no-store`。
5. **响应头带汇总**：`X-Export-Days`/`X-Export-Pins`/`X-Export-Unpins`/
   `X-Export-Users`/`X-Export-Sessions`，前端不需要再解析 CSV 才能提示导出结果。
6. **前端按钮放在统计卡**：`PinAuditStatsCard` 自己管理导出中/成功/失败状态，
   使用页面已应用的 `filters` 与 `days`；导出响应回来后按当前过滤 key 判断是否
   展示提示，过滤已变化时不显示旧提示。页面不新增状态，保持 ≤300 行。
7. **失败语义**：统计查询 `SQLAlchemyError` → 503 `DATABASE_UNAVAILABLE`；导出
   失败只影响导出提示，不影响列表/统计。旧后端没有该端点时显示导出失败。
8. **无迁移**：只新增只读端点，复用 `session_pin_audits` 与
   `idx_session_pin_audits_time`。

## 后果

- 管理页的统计数字可以直接下载，字段与恢复审计统计导出一致，便于合并分析。
- 统计与导出是两次独立查询；导出瞬间与页面统计可能相差一条并发写入，页面接受。
- 导出没有下载审计（谁在什么时候导出了什么）；这与恢复审计/审批导出的现状一致，
  后续若需要审计导出行为，应单独建表并单独设计，不塞进本端点。
- 不做异步导出/XLSX 多工作表；CSV 为长表，透视前需按 `section` 过滤。
- 统计导出不改变列表导出；两个按钮的过滤/日期范围由同一组已应用条件驱动。

## 验证

- 后端 `test_admin_pins.py`：新增 `test_session_pin_audit_stats_export`，覆盖
  `days=7&user_id=u_102&action=unpin` 的响应头、CSV 表头、`meta`/`summary`/`daily`
  行；`stats/export` 加入 403、非法参数与 503 用例。
- 前端 `pinAudits.test.ts`：按天数+过滤导出仍带 `days`；日期范围只发
  `created_from`/`created_to`；解析汇总响应头。
- 实测：默认 **517 passed + 40 skipped**；Postgres-only **554 passed + 3 skipped**；
  Postgres + Redis **557 passed**；`ruff check` / `ruff format --check` 200 files /
  `mypy app` 116 files；前端 **26 files / 127 tests**、tsc、oxlint 0/0、oxfmt 133 files、
  `pnpm build` 2933 modules/346ms 通过。
- 本次无新迁移，未执行迁移往返；`0022` 保持不变。

## 待定

- 统计卡图表化（折线/柱状）与缓存/物化；
- 下载审计（导出行为本身留痕）、异步导出与 XLSX；
- 统计与列表的严格同一快照（目前接受一次并发写入的偏差）。
