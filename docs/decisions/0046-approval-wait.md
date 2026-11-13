# ADR-0046：审批等待时长回放

- 状态：已采纳（W6 后补）
- 日期：2026-11-13
- 相关：[ADR-0035](0035-run-timeline-replay.md)（运行过程回放）、[ADR-0045](0045-timeline-filter-summary.md)（筛选与工具耗时）

## 1. 背景

运行过程能回放审批的发起与决议，但只显示状态和理由，不显示**等了多久**。工具耗时（ADR-0045）
只是机器执行时间；涉及写操作时，人审批的等待往往才是整轮里最长的一段。用户问「这轮为什么慢」
时，工具耗时 12ms、审批等了两小时，现在的界面完全看不出来。

`approval.required` 与 `approval.resolved` 事件都带服务端 `ts`，差值就是等待时长；不需要新表、
迁移或额外查询。ADR-0045 的待定里已经把这个缺口记成「需要审批事件带 requested_at/resolved_at
的差值，当前时间线不计算」。

## 2. 备选方案

| 方案 | 结论 |
|---|---|
| 前端用 `requested_at` / `resolved_at` 自己相减 | 可行，但把「什么算负值、缺字段怎么办」的规则复制到展示层；接口直接给语义字段更稳 |
| 返回 `requested_at` 和 `resolved_at`，不返回 `waited_ms` | 两个时间给调试用，等待时长仍由前端每次算，容易各自实现 |
| 用 `expires_at - requested_at` 当等待时长 | 否：那是超时上限，不是实际等待；审批可能提前通过 |
| 从 `approvals` 表读 `created_at/resolved_at` | 否：时间线是事件投影，混用数据库时间会和回放的其他字段不同源 |
| 事件差值 + 服务端计算（采纳） | 是：两个事件同一时间源，无迁移，历史 run 直接可算 |

## 3. 决策

1. **审批项新增两个可选字段**：`requested_at`（`approval.required` 的事件时间，ISO 字符串）与
   `waited_ms`（从发起到决议的毫秒数）。`GET /runs/{id}` 与批量会话详情同时生效。
2. **只对已决议的审批给 `waited_ms`**：待审批的项没有「等待了多久」的终点；不给 0，也不拿
   「当前时间」去猜。前端对 pending 不显示等待。
3. **差值非负才写入**：`resolved` 时间早于 `required` 属于脏数据/时钟异常，直接省略
   `waited_ms`，不显示负数。孤儿 `approval.resolved`（没有对应 required）仍按 ADR-0035 忽略。
4. **不进入汇总与「最慢」**：汇总仍是工具执行时间之和；审批等待是人的时间，混进「工具耗时」
   会把两种延迟画成一个数。本轮只在单条审批卡片上展示。
5. **展示格式复用 `formatDuration`**：与工具耗时同一套 `ms / 1.2s / Xm Ys / Xh Ym / Xd Yh`，
   避免两套口径；审批等待可能跨小时或天，因此格式化函数要能进到小时/天，不能显示成 `1440m 0s`。
6. **身份口径不变**：仍然不返回 `resolved_by` / `scope`；等待时长不泄露审批人。
7. **无迁移、无回填**：历史事件本来就带 `ts`；旧 run 打开时直接按事件计算。不新增定时任务。

## 4. 后果

- 「为什么慢」能拆成两段：工具执行耗时与人工审批等待；审批卡片显示「等待 2m 3s」。
- 超出保留期、事件已清理的 run 仍和时间线一起不可用，不会因为新字段改变可见性。
- 等待时长来自事件写入时间，不是审批系统的精确受理时间；秒级误差可接受。
- 汇总行仍只显示工具耗时，不会把审批等待加进去；要看审批等待需展开对应审批项。
- `waited_ms` 是整数毫秒，前端沿用 `formatDuration`，不会出现负数或 `1m 60s`。

## 5. 验证

- 后端：新增 `test_build_timeline_reports_approval_wait`（90 秒差值）与
  `test_build_timeline_omits_negative_approval_wait`（决议早于发起的脏数据不产出负数）；
  既有审批合并用例补 `requested_at` / `waited_ms` 断言。
- 默认 `uv run pytest -p no:warnings`：**471 passed + 35 skipped**（25.87s）；
  真实 Postgres **503 passed + 3 skipped**（53.49s）；Postgres + Redis **506 passed**
  （53.63s）。`ruff check` 通过、`ruff format --check` 186 files、`mypy app` 110 files。
- 前端：`tsc --noEmit` 通过、`pnpm test` **73 tests / 15 files**、`oxlint` 0/0
  （66 files、231 rules）、`oxfmt --check` 74 files、`pnpm build` 712ms。
- 不改表、不改事件类型、不改保留清理；不重跑 RAG 与多轮评测。

## 6. 待定

- 是否把「人工审批等待」单独汇总成一行（与工具耗时并列，而不是相加）。
- 待审批项是否显示「已等待 X」——需要服务端按请求时间算，且每次查看时间不同。
- 是否给审批等待设阈值/告警（例如超过 4 小时）。
- 是否用审批系统的真实受理时间替代事件时间；当前事件时间是唯一可用来源。
- 跨 run 的审批等待统计（审批人视角/流程瓶颈）留给管理员视图 —— ✅ 已由
  [ADR-0048](0048-approval-stats.md) 兑现（`GET /approvals/stats` 的积压与窗口等待聚合）。
