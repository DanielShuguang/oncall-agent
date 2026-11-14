# ADR-0062：会话恢复审计 CSV 导出

## 背景

`GET /admin/session-restores` 已支持按 `user_id`/`session_id` 过滤与 keyset 分页
（ADR-0059/0060/0061），但管理员要拿审计数据做交接、对账或离线留档时，只能一页页
翻（`limit` 最大 200）。审计保留 365 天，逐页拼接既慢又容易漏，且没有稳定的
「一次导出当前过滤结果」的口径。

## 备选方案

| 方案 | 为什么否决 |
|---|---|
| 复用列表接口，前端循环翻页拼接 | 仍是 N 次请求；中途失败得到半份文件，无法判断完整性 |
| 导出不设上限 | 365 天审计量不可控，同步请求可能拉爆内存/连接 |
| 异步导出任务 + 对象存储 | 需要队列、任务状态与文件清理，当前私有化部署不引入 |
| 只导出 `user_id` 计数汇总 | 审计复盘需要逐批次的时间、会话 id 与计数，汇总不够 |
| 新增下载审计表 | 当前需求是「谁能导出」，不是「谁下载过」；先不做 |

## 决策

1. 新增 `GET /admin/session-restores/export`，管理员只读；过滤参数与列表一致
   （`user_id`/`session_id`，各 1–64），不接收 `cursor`/`limit`。
2. 同步导出最多 5000 条：内部取 `limit + 1` 判断截断，响应头
   `X-Export-Count`/`X-Export-Truncated` 显式告知，不因超限返回错误。
3. CSV 列为 `audit_id, user_id, restored_at, requested_count, restored_count,
   session_ids`；`session_ids` 用 JSON 数组保留顺序。不导出会话正文、消息或
   工具参数，避免把敏感内容带进表格。
4. 与审批导出一致：UTF-8 BOM、CRLF、时间 ISO 8601 UTC、`= + - @ \t \r` 开头
   前置单引号防公式注入，`Cache-Control: no-store`。
5. 抽出 `app/core/csv.py` 的 `csv_cell`/`csv_document`，审批导出改为复用；
   两个导出不再各维护一份公式注入防护。
6. 无迁移、无新索引；沿用 `session_restore_audits` 的
   `(restored_at, id)` 排序与 `user_id`/`session_id` 过滤。不做异步导出、
   总数、下载审计与前端管理页。

## 后果

- 导出是同步请求，最坏要读 5001 行；超过 5000 条时只拿到前 5000 条，
  必须看 `X-Export-Truncated`，不能把文件当成全量。
- 导出的是「当前时刻」的审计快照；导出期间新增的恢复不会出现在文件里。
- 管理员可以导出所有用户的审计（与列表权限一致）；下载动作本身不落审计。
- CSV 单元格可能被 Excel/WPS 当公式，已统一前置单引号；但 CSV 仍不是防篡改
  证据，审计表本身才是。
- 共享 `app/core/csv.py` 后，审批导出的行为不变；新增导出只需提供表头与行。

## 验证

- 默认 **496 passed + 40 skipped**；Postgres **533 passed + 3 skipped**；
  Postgres + Redis **536 passed**；`ruff check` / `ruff format --check`
  （194 files）/ `mypy app`（113 files）通过。
- 前端未改，沿用 **81 tests / 16 files**、`oxlint` 0/0（68 files）、
  `oxfmt --check` 76 files、`pnpm build`。
- 新增 `test_export_session_restores_csv`（管理员权限、空结果、表头/过滤/JSON 数组/
  响应头/BOM/CRLF/公式注入）与 `test_export_session_restores_truncates`（超上限截断）；
  原有审批导出测试继续覆盖共享 CSV helper 的转义与公式注入。
- 无迁移；`session_restore_audits` 的写入/保留路径未改。

## 待定

- 异步导出与下载审计（谁在何时导出了哪些过滤条件）；
- 审计总数/跳页（总数已由 ADR-0064 补上，跳页仍未做）；
- 导出列是否增加 `requested_count - restored_count` 的显式未恢复数；
- 大租户下按 `restored_at` 范围分段导出，避免 5000 条上限截断。
