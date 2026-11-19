# ADR-0099：工具配置变更历史 CSV 导出

- 状态：已接受
- 日期：2026-11-19
- 相关：ADR-0037（工具配置变更历史）、ADR-0094（CSV 导出下载审计）、ADR-0097（导出内容哈希）、ADR-0098（历史日期范围）

## 背景

ADR-0037 的变更历史只能在 ToolsPage 的 Dialog 里逐条看，ADR-0098 又加了 UTC 日期范围。管理员需要把一段时间的配置变更交给审计/归档时，只能手工抄录；翻页/截图都不能作为可核对的快照。

ADR-0098 的「待定」也明确写了导出能力留待后续。现在补一个与已有 6 类业务导出同构的入口：同一套过滤、同一套 CSV、同一套下载审计。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 复用 `/admin/export-audits` 导出工具历史 | 不采纳：导出审计记录的是「谁导出了什么」，不是工具配置本身；两者语义不同 |
| 前端把当前列表拼 CSV | 不采纳：只能导出已加载的 20 条，且无法保证服务端过滤口径 |
| 异步导出 + 产物下载 | 不采纳：当前最大 5000 行，同步生成足够；异步会引入任务表和临时文件清理 |
| 同步 CSV，最多 5000 行 | 采纳：与审批/恢复/置顶导出一致，不新增基础设施 |

## 决策

1. 新增第 8 种导出资源 `tool_setting_history`。`export_audits.resource` 的 CHECK 扩展为 8 种，迁移 `0026` 只改 CHECK；降级先删除该资源的审计行，再恢复 7 种枚举。
2. 新增 `GET /admin/tools/{name}/history/export`，只允许管理员；参数与 `/history` 相同（`changed_from` / `changed_to`，UTC 自然日，两端同时提供，最多 365 天），不接收 `limit` / `cursor`。
3. CSV 固定六列：`tool_name,changed_at,changed_by,source,before,after`；`before` / `after` 用 `json.dumps(..., ensure_ascii=False, sort_keys=True)` 序列化，空快照写空字符串；复用 `csv_document` 的 BOM/CRLF/公式防护。
4. 最多导出 5000 行。查询 `MAX_EXPORT_ROWS + 1` 判断截断；超过时只返回前 5000 行，并在 `X-Export-Truncated: true` 与下载审计 `truncated=true` 同时标注。不提供总数/游标。
5. 导出本身写下载审计：资源 `tool_setting_history`，`filters` 只保留 `tool` 与两端日期，`row_count` 为实际返回行数，`content_sha256` 为返回 CSV 的 SHA-256。审计写入失败返回 503，不返回没有留痕的下载。
6. 文件名使用 `tool-history-{safe_name}-{UTC}.csv`；工具名中非 ASCII 字母数字/`-_` 的字符替换为 `_`，避免引号、路径或非 latin-1 字符进入 `Content-Disposition`。
7. 前端导出使用「已应用」的筛选，而不是输入框草稿；切换筛选或关闭 Dialog 会失效在途导出，避免旧响应覆盖新视图。提示实际导出行数，截断时明确说明只含前 5000 条。

## 后果

- 好处：历史窗口可离线归档，且每次下载都能在导出审计里反查谁、何时、用什么过滤条件导出了多少行；CSV 内容哈希可核对。
- 代价：单次最多 5000 行，窗口更大时只拿到前 5000 行；不提供总数，管理员需要看截断标记。工具历史没有分页契约，导出也不补分页。
- 审计生命周期：`export_audits` 仍按 ADR-0095 的 365 天独立清理；导出工具历史不会延长其保留期。
- 旧记录：`content_sha256` 为空的旧审计仍可列出；新导出才有哈希。
- 权限：只读管理员接口；普通员工 403。工具下线后仍可按旧名字查/导出历史（数据未删）。

## 验证

- 后端：`test_tool_history.py` 覆盖导出、403、单端 422、CSV 表头/BOM、审计过滤/行数/哈希，以及非 ASCII 工具名生成可写响应头；默认 `pytest` **531 passed + 41 skipped**（tests=572），PG-only **569 passed + 3 skipped**，PG+Redis **572 passed**。
- 迁移：`0026` 的 upgrade → `alembic check` → downgrade `0025` → upgrade `0026` 通过，无漂移；降级会丢失 `resource=tool_setting_history` 的审计行。
- 前端：`pnpm test` **27 files / 135 tests**、`lint 0/0`（131 files）、`format:check` 139 files、`build` 2938 modules 通过；`exportToolHistoryCsv` 的 URL/响应头用例已补。
- 静态检查：`ruff check`、`ruff format --check` 208 files、`mypy app` 119 files 通过。

## 待定

- 是否给工具历史加分页/总数，让导出不必截断。
- 异步导出/ XLSX / 产物保留；当前明确不做。
- 是否把「导出工具历史」从管理员扩展到审计员角色；当前只有 admin。
