# ADR-0092：置顶审计按小时分布

- 状态：已采纳
- 日期：2026-11-18
- 相关：ADR-0058（审批统计按小时分布）、ADR-0087（置顶审计按日统计）、ADR-0089（统计跟随过滤）、ADR-0090（统计 CSV 导出）

## 背景

置顶审计统计已经能回答「窗口内置顶/取消了多少、涉及谁」，也按 UTC 自然日给出
稀疏日趋势（ADR-0087/0089）。但管理员排值班、判断「是不是交接班时段集中发生」
时，按日的粒度不够：同一天上午和晚上的活动被合并，无法看出小时级分布。

审批统计在 ADR-0058 已经做了 UTC hour 分布，使用同一套窗口与过滤；置顶审计当时
只在 ADR-0089 的「待定」里记了「按小时分布/图表库」。这一轮补上小时分布，不改
窗口、过滤或权限语义。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 按「日期 × 小时」返回（最多 365×24 行） | 精确到某天某小时，但响应和前端都过大；365 天窗口下大部分是空桶，管理页不可读 |
| 只在前端从 `daily` 推算小时 | `daily` 已经把小时合并，信息已丢失；重新拉列表再前端聚合会多一次大查询 |
| 单独 `/stats/hourly` 端点 | 与 `/stats` 重复窗口/过滤/权限校验，多一套契约；统计卡需要两次请求并处理竞态 |
| 在 `/stats` 加 `hourly` 字段（采用） | 与 `daily` 同一次窗口、同一次查询，前端一次请求；响应最多 24 项 |
| 引入图表库 | 管理页只需要看分布；图表库增加依赖与视觉口径，当前列表/标签足够 |

## 决策

1. **`hourly` 是窗口内按 UTC 小时（0–23）聚合的稀疏列表**，不是「日期 × 小时」。
   同一小时跨多天的活动合并；只返回有活动的桶，不补零。
2. **与 `daily` 同一窗口、同一过滤**：`user_id`/`session_id`/`action`/日期范围
   与列表同口径；`hourly` 的 `pins`/`unpins` 之和分别等于汇总
   `SessionPinAuditStats.pins`/`unpins`。
3. **存储层统一返回**：`SessionPinAuditStats` 增加
   `hourly: tuple[SessionPinAuditHourStats, ...]`；内存实现按
   `created_at.astimezone(UTC).hour` 分桶，Postgres 用
   `extract(hour from timezone('UTC', created_at))` 分组；两者都只排序、不补零。
4. **接口新增字段，不新增参数**：`GET /admin/session-pins/stats` 响应增加
   `hourly: [{hour, pins, unpins}]`；旧客户端忽略未知字段。`/stats/export` 的
   CSV 增加 `section=hourly` 行，`key` 仍是 `pins`/`unpins`，`day` 列放
   `HH:00`（保持固定四列，避免破坏 ADR-0090 的契约）。
5. **前端只展示有活动的时段**：统计卡在日趋势下增加「按小时（UTC）」标签，
   每个桶显示 `HH:00 · 置顶 N / 取消 M`；不引入图表库，不做 24 小时零填充。
   旧后端没有 `hourly` 时按空数组降级，不报错。
6. **无迁移**：只加响应字段与聚合查询，复用 `idx_session_pin_audits_time`。
7. **口径限制**：小时是 UTC，不是部署本地时区；跨时区查看时需自行换算。不做
   「某天某小时」的热力图，也不做统计缓存/物化。

## 后果

- 管理页多一行小时分布，值班/交接班问题可以直接看；响应最多 24 项，365 天窗口
  也不会膨胀。
- `hourly` 与 `daily` 是同一批记录的两个切面，两个方向的求和都等于汇总；不会出现
  「日趋势和小时分布对不上」。
- CSV 的 `day` 列在 `hourly` 段承载 `HH:00`，这是长表四列约束下的取舍；消费方需
  按 `section` 区分日期与小时，已在 docs/03 写明。
- 不补零意味着「没有活动的小时」不出现；前端不能把缺失小时当成数据错误。
- 仍不回答「哪一天的那个小时」；需要时另做热力图/明细导出，不在本 ADR 范围。

## 验证

- `server/tests/test_store_contract.py`：窗口汇总与过滤后的 `daily`/`hourly` 求和
  分别等于 `pins`/`unpins`；空窗口 `hourly=()`。
- `server/tests/test_admin_pins.py`：`/stats` 响应含 `hourly`，小时在 0–23，
  `pins`/`unpins` 求和等于汇总；`/stats/export` CSV 含 `section=hourly` 两行，
  小时标签为 `HH:00`。
- 前端 `web/src/api/pinAudits.ts` 增加 `SessionPinAuditHourStats` 与可选 `hourly`
  类型；统计卡只渲染有活动的桶，旧后端缺失字段按空数组处理。
- 实测：默认 **517 passed + 40 skipped**、PG-only **554 passed + 3 skipped**、
  PG+Redis **557 passed**；`ruff check` / `ruff format --check` 200 files、
  `mypy app` 116 files；前端 **26 files / 128 tests**、`tsc --noEmit`、`oxlint`
  0/0（127 files/232 rules）、`oxfmt --check` 135 files、`pnpm build` 通过。
- 本次无新迁移，未执行迁移往返；`0022` 保持不变。

## 待定

- 按「日期 × 小时」的热力图与图表库；
- 统计缓存/物化视图（当前窗口最多 365 天，查询成本可接受）；
- 多副本下的时间边界与下载审计（仍属 ADR-0090 的待定项）。
