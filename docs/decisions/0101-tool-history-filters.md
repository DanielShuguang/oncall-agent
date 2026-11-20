# ADR-0101：工具配置变更历史按变更人/来源过滤

- 状态：已采纳
- 日期：2026-11-20
- 相关：[ADR-0037](0037-tool-setting-history.md)、[ADR-0098](0098-tool-history-date-range.md)、
  [ADR-0099](0099-tool-history-export.md)、[ADR-0100](0100-tool-history-pagination.md)

## 背景

ADR-0100 给工具配置变更历史加了 keyset 分页和首屏总数，但查询仍只能按工具名、UTC 日期窗口
收窄。管理员复核一次权限矩阵调整或某个人的操作时，只能翻完整页再肉眼筛；导出的 CSV 也只能
按日期范围，无法直接交给审计方「某人在某窗口内改了哪些工具」。

ADR-0100 的「待定」已列出变更人/来源过滤。现有 `(tool_name, changed_at DESC)` 索引先按工具
收窄，再在工具内做等值过滤；数据量只有治理写入，不需要为此加新索引。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 前端在已加载页内过滤 | 分页与 `total` 会失真；导出无法复用；不采纳 |
| 新增 `/tools/{name}/history/filter` 专线 | 与现有列表/游标语义分叉；不采纳 |
| 在 `/history` 与 `/history/export` 增加等值参数 | 列表、总数、游标、导出共用一套语义；采纳 |
| 同时加上模糊搜索/多选变更人 | 需求未出现，先保持精确匹配；不采纳 |

## 决策

1. **只做精确等值过滤**：`changed_by` 匹配完整 `user_id`（1–64 字符）；
   `source` 只接受 `tool`/`matrix`。不做前缀、模糊或多选。
2. **过滤下沉到 store**：`history` 与 `count_history` 都接收 `changed_by`/`source`，
   内存先按工具、日期、过滤条件筛再倒序截断；PG 在 `WHERE` 中追加等值条件。`total`
   是过滤后的数量，不是全工具数量。
3. **游标绑定完整筛选**：游标指纹纳入工具名、日期窗口、`changed_by`、`source`。改任一
   筛选后复用旧游标返回 `400 INVALID_CURSOR`，避免跨集合翻页。
4. **导出复用同一过滤**：`/history/export` 接收相同参数，CSV 只含过滤后的记录；
   下载审计的 `filters` 记录 `tool`、日期、`changed_by`、`source`。
5. **前端区分草稿与已应用**：Dialog 内可改日期、变更人、来源；点「应用」才发请求，
   列表与导出都用最近一次已应用值；「清除」一次重置全部过滤。
6. **不新增迁移**：不建表、不改 CHECK；过滤值是现有列。
7. **不新增索引**：先沿用 `(tool_name, changed_at DESC)`。若真实数据量证明按人过滤慢，
   再评估 `(tool_name, changed_by, changed_at DESC)`，不在本 ADR 预建。

## 后果

- 好处：管理员能直接定位「谁改的、从哪改的」，列表总数/分页/导出保持同一口径。
- 代价：`changed_by` 是精确匹配，输错一个字符就是空结果；UI 只能提示「精确匹配」。
- 代价：没有新索引，工具记录很多且按人过滤占比高时可能扫更多行；当前写入量可接受。
- 过滤参数为空字符串时按「未提供」处理（前端不会发送空串）；`source` 非法值由 FastAPI
  返回 422。

## 验证

- 内存 store：日期窗口 + `changed_by` + `source` 过滤、`count_history` 同口径。
- PG store：`history`/`count_history` 的变更人/来源过滤，跨工具隔离。
- API：`changed_by` 过滤、`source=matrix` 过滤、组合过滤、非法 `source` 422；
  改 `changed_by` 复用旧游标 400；导出按过滤集合写 CSV，`X-Export-Count` 与审计
  `filters` 一致。
- 前端：API 参数顺序、Dialog 应用/清除、导出使用已应用过滤；`tsc`/`lint`/`test`/`build`。
- 全量：默认 **533 passed + 42 skipped**、PG-only **572 passed + 3 skipped**、
  PG+Redis **575 passed**；`ruff check` / `ruff format --check` 208 files / `mypy app` 119 files；
  前端 27 files / 138 tests、lint 0/0（133 files）、`oxfmt --check` 141 files、`build` 2940 modules。
- 无迁移，迁移链仍停在 0026。

## 待定

- 是否需要按变更人前缀/多选过滤；当前只做精确单值。
- 是否增加 `(tool_name, changed_by, changed_at DESC)` 索引；先观察真实查询计划。
- 是否把 `source` 扩成更多枚举值；扩值需要同步 CHECK、API 校验和前端下拉。
