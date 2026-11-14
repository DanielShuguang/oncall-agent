# ADR-0051：审批统计按工具/审批人分组

- 状态：已采纳
- 日期：2026-11-13
- 相关：[ADR-0048](0048-approval-stats.md)（审批积压与等待统计）、[ADR-0050](0050-approval-trend.md)（按日趋势）

## 1. 背景

ADR-0048 给了审批人一组窗口汇总：待办数、最久已等、已决议数、平均/最长等待；
ADR-0050 又补了 UTC 日粒度的 `daily`。但这些数字只回答「整体压了多少」，
回答不了「压在哪个工具上」「哪位审批人手里最慢」。

`approvals` 表本身有 `tool_name` 和 `resolved_by`，`GET /approvals` 也逐条返回；
但列表分页、且前端聚合需要先拉全量，既慢又容易和统计窗口不一致。
待办没有审批人归属（还没人处理），所以「按审批人分组」只能覆盖已决议的单。

## 2. 备选方案

| 方案 | 否决原因 |
|---|---|
| 前端拉列表后自己聚合 | 列表分页、默认 50 条；窗口/排序/分页都无法和统计对齐 |
| 每个维度各开一个接口 | 两份聚合、两份鉴权、两份文档，后续加维度继续翻倍 |
| 预计算表按小时/天落库 | 需要新表、迁移、回填与失效逻辑；当前审批量不值得 |
| 在现有 stats 上加可选 `group_by` | 一次请求只多一组聚合，口径与窗口汇总共用；**采纳** |

## 3. 决策

1. `GET /api/approvals/stats?days=&group_by=`，`group_by` 可选，
   取值 `tool` / `approver`，默认不分组；仍仅审批人角色可读。
2. 分组只聚合**窗口内已决议**（`approved` + `rejected`）的审批；
   `pending` 没有审批人归属、`expired` 不是人工决议，都不进入分组。
   各分组 `decided_count` 之和等于同一响应的 `decided_count`（未截断时）。
   等待时长按 0 下限处理（决议早于创建的脏数据），内存与 Postgres 口径一致。
3. 分组键：`tool` 用 `tool_name`；`approver` 用 `resolved_by`，
   缺失（老数据/系统决议）归入 `unknown`。
4. 按 `decided_count` 降序、分组键升序取前 20 组；超过 20 组时
   `groups_truncated = true`，此时分组之和不等于 `decided_count`。
5. 不分组时 `groups` 为空数组、`groups_truncated = false`，响应形状稳定。
6. 聚合在存储层完成：内存按 `(tool_name | resolved_by)` 分桶后排序；
   Postgres `GROUP BY` 同一窗口条件，`count/avg/max` 一次查回。
   无新表、无迁移、无新索引。
7. 前端在审批中心窗口选择旁加「不分组 / 按工具 / 按审批人」下拉，
   分组结果以紧凑表格放在「按日决议」之后；截断时提示只显示前 20 组。
8. 仍不返回逐条 `resolved_by`；`approver` 分组的 key 是审批人 `user_id`，
   只给审批人看聚合数字。不做告警、不做按状态/优先级的下钻。

## 4. 后果

- 分组请求比普通统计多一条聚合查询（待办、窗口汇总、按日趋势、分组共四条）；
  审批数据量小，当前可接受；真到十万级再评估索引或预计算。
- `approvals` 上 `tool_name` / `resolved_by` 没有索引；当前按窗口全表聚合，
  代价与 ADR-0048 的总量聚合同一量级。
- `unknown` 分组会出现（历史数据没有 `resolved_by`，或系统过期）；
  管理页直接显示原始 `user_id`，因为系统没有用户目录。
- 分组最多 20 组，超过时只看得到头部；不做分页；统计聚合导出已由 ADR-0068 补上。
- 统计仍是请求时快照；页面停留不会自动刷新。

## 5. 验证

- 默认 `pytest` **479 passed + 36 skipped**（19.76s）。
- 真实 Postgres **512 passed + 3 skipped**（46.22s）；
  Postgres + Redis **515 passed**（46.37s）。
- `ruff check` 通过、`ruff format --check` **187 files**、`mypy app` **110 files**。
- 前端 `tsc --noEmit` 通过、**73 tests / 15 files**、`oxlint` 0/0（66 files、
  231 rules）、`oxfmt --check` 74 files、`pnpm build` 238ms。
- 新增/覆盖：内存分组（tool/approver、`unknown` 不参与空表）、21 组截断、
  API `group_by` 合法/非法值、PG 分组 SQL、PG 负等待夹到 0。

## 6. 待定

- 是否按状态/风险等级继续下钻，或把分组结果做成可点击筛选。
- 是否加 `(resolved_by, resolved_at)` / `(tool_name, resolved_at)` 索引；
  需要先有真实量级与查询计划。
- 是否需要按小时趋势、告警阈值、CSV 导出；按小时趋势见 ADR-0058，统计聚合导出于 ADR-0068 实现。
- 审批人 `user_id` 到姓名的映射（需要身份目录，等 IdP）。
- 超过 20 组时的分页或「其他」聚合。
