# 0068 审批统计聚合导出 CSV

## 背景

审批统计接口已经返回积压、等待、按日/按小时分布与按工具/审批人分组（ADR-0048、
ADR-0050、ADR-0051、ADR-0058），前端也把这些数字拆成卡片和表格展示。但页面只能看，
不能带走：交接、周报、容量评估和离线复核仍要对着屏幕抄数字，或者截图拼进表格。
审批列表有逐条 CSV 导出（ADR-0056），但「统计聚合」与「逐条审批」是两种形状，
不能拿列表导出去复原汇总。

ADR-0058 的待定项明确记着「统计聚合导出（与逐条 CSV 不同形状）」。本 ADR 补这一项。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 只导出审批列表 CSV | 否决 | 形状不对：列表没有积压、平均等待、日/小时分布与分组聚合 |
| 导出 JSON | 否决 | 统计是给人看的，Excel/表格是主要消费场景；JSON 还要再转一次 |
| 一文件多工作表（XLSX） | 否决 | 需要引入写 Excel 的依赖，当前 CSV helper 已够用 |
| ZIP 内放多个 CSV | 否决 | 下载与解压多一步，收益不抵复杂度 |
| 前端把页面上的数字拼成 CSV | 否决 | 重复实现格式化/公式转义；分页/窗口变化时容易拼错 |
| 异步导出任务 | 否决 | 统计有界（最多 90 天、24 个小时、20 个分组），同步生成即可 |
| 一个长表，`section` 区分汇总/日/小时/分组 | **采纳** | 复用现有 CSV helper；一次下载拿到全部口径；Excel 可筛选/透视 |

## 决策

1. **新增 `GET /approvals/stats/export?days=&group_by=`**，与统计接口使用同一组参数、
   同一身份范围：仅审批人可读，普通员工 403，数据库不可用 503。不接收 `cursor`/`limit`。

2. **统计导出是一张长表**，列固定为：

   ```text
   section,key,day,hour,count,avg_wait_ms,max_wait_ms,value
   ```

   - `meta`：`days`、`group_by`（`none` 表示不分组）。
   - `summary`：`pending_count`、`oldest_pending_age_s`、`decided_count`、`avg_wait_ms`、
     `max_wait_ms`、`groups_truncated`；数值放 `value`。
   - `daily`：`key`/`day` 都是 UTC 日期 `YYYY-MM-DD`，`count`/`avg_wait_ms` 为该日决议；
     稀疏，不补零。
   - `hour`：`key` 为两位小时 `00`–`23`，`hour` 为整数，`count`/`avg_wait_ms` 为该小时决议；
     稀疏，不补零。
   - `group`：`key` 为工具名或审批人 `user_id`（缺失为 `unknown`），`count`/`avg_wait_ms`/
     `max_wait_ms` 为分组聚合；`group_by=none` 时没有 `group` 行。

3. **分组截断必须显式可见**：分组最多 20 组。截断时 `summary.groups_truncated=true`，
   响应头 `X-Export-Groups-Truncated: true`；不能把前 20 组当成全量。

4. **窗口与分组元数据同时出现在内容与响应头**：`meta.days` / `meta.group_by` 便于
   文件离开页面后仍能解释口径；响应头 `X-Export-Days` / `X-Export-Group-By` 便于
   前端提示与自动化校验。

5. **复用 `app/core/csv.py` 的 `csv_document`**：UTF-8 BOM + CRLF、ISO 8601 UTC、
   以 `= + - @ \t \r` 开头的单元格前置单引号。分组键来自工具名/`user_id`，同样按
   不可信文本处理，不能直接写进 CSV。

6. **同步导出、不设条数上限**：统计结果规模由 `days`/`group_by` 决定（90 天 × 24 小时 +
   20 组），不需要异步任务或下载审计；导出是当前窗口的快照，不是跨天归档。

7. **前端按钮使用当前统计窗口与分组**，文件名 `approval-stats-{days}d-{none|tool|approver}.csv`；
   切换窗口/分组时失效在途导出并清空提示；成功提示窗口、分组与截断状态。

## 后果

- 统计终于可离线复核；CI/对账可以直接读 CSV 的 `section`，不用解析 JSON。
- 长表比多工作表更难「一眼看懂」，需要在表头/文档里解释 `section`；这是接受的可读性
  代价，换取无新依赖、一个文件表达全部口径。
- 统计窗口由多条独立查询组成（与统计接口相同），导出与页面不是严格同一快照；但导出是只读
  快照，允许这个边界。
- 分组被截断时导出仍只有前 20 组；`groups_truncated` 与响应头负责告知，不静默截断。
- 不记录「谁在何时导出了什么」，也不做异步任务/对象存储；这些留在待定。

## 验证

- `tests/test_approval_stats.py`：统计导出表头/`meta`/`summary`/`daily`/`hour`/`group`
  行、BOM、CRLF、公式前缀转义（工具名 `=cmd` 被转成 `'=cmd`）、响应头、403、503；
  分组超过 20 组时只输出前 20 组，内容和响应头都标记截断。
- 默认 `pytest`：**502 passed + 40 skipped**；Postgres：**539 passed + 3 skipped**；
  Postgres + Redis：**542 passed**。
- `ruff check` / `ruff format --check`（194 files）/ `mypy app`（113 files）通过。
- 前端：**86 tests / 17 files**、`tsc --noEmit`、`oxlint` 0/0（72 files）、
  `oxfmt --check` 80 files、`pnpm build` 通过。
- 无迁移。

## 待定

- 下载审计（谁在何时导出了哪些窗口/分组）。
- 异步导出与对象存储（当前数据量不需要）。
- 多工作表 XLSX、CSV 列裁剪/自定义列。
- 导出与统计接口共用同一快照（当前是两次独立查询）。
- 统计缓存/物化视图。
