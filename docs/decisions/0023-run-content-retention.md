# 0023 · run 正文按时间保留：到期清空 `input/output`，只留摘要

- 状态：已采纳（W6 后加固）
- 日期：2026-11-10
- 相关：[docs/02-data-model.md](../02-data-model.md)、[docs/03-api-contract.md](../03-api-contract.md)、[docs/07-frontend-design.md](../07-frontend-design.md)、[docs/09-deploy-private.md](../09-deploy-private.md)、[ADR-0017](0017-stale-run-recovery.md)、[ADR-0020](0020-multi-turn-context.md)、[ADR-0021](0021-data-retention.md)、[ADR-0022](0022-run-content-visibility.md)

## 背景

ADR-0021 让事件与计量有了执行者，但它明确把 `runs` 行留在原地：

> `runs`：运行列表、失败率、成本口径与多轮上下文都依赖；`input/output` 是产品数据，
> 不是日志。run 级保留是另一个决策。

ADR-0022 补上了「**谁能看**」：引用文档被改窄后，旧回答在详情、事件、重放与多轮历史里
都不再展示。但它没有回答「**留多久**」——可见性改回去内容就恢复，说明回收只是读时判定，
正文一直躺在库里。

于是私有化现场最常被问的两个问题里，第二个仍然没有答案：

1. 数据会不会出内网？——不会（ADR-0015）。
2. 用户的问题和回答留多久？——除了事件 180 天与计量 180 天之外，**`runs.input/output` 永久**。

`input` 是用户敲进来的问题，可能是「财务系统登录不上，工号 A12345」；`output` 是回答正文。
两者都是产品数据，不是运维日志，不能靠「事件清理」顺手带走。

动手前还要先解决一个耦合点：**回答正文在事件里也有一份**（`message.delta` 的增量、
`message.completed.text`）。只清 `runs` 不清事件，等于把同一段正文留在事件表里，
保留期形同虚设。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 直接删 `runs` 行（级联事件、审批、计量） | 运行列表、失败率、成本口径、多轮上下文与审批审计一起没（ADR-0021 已否决，这次不翻案） |
| 只清 `output`、保留 `input` | 问题本身可能含工号、主机名、故障细节；「删一半」在合规上说不通，也说不清口径 |
| 把正文挪出 `runs`，只存事件 | 事件 180 天就整场删了，正文保留期反而更短；详情/多轮还要扫事件，性能更差 |
| 与事件清理合并成一步（清事件时顺手清正文） | 两个策略耦合死了：现场可能想「审计事件只留 180 天、问答留 365 天」，或者反过来；独立开关才表达得出来 |
| 定时任务 + 独立 TTL + 标记 + 自己的部分索引 | 改动小、可 dry-run、幂等、与事件清理互不影响；正文保留期不允许短于事件（配置层强制），耦合点用校验表达而不是用实现锁死 |

## 决策

### 1. 只清终态 run 的正文，同事务写标记

新增 `runs.content_pruned_at`（迁移 0012）与 `RunStore.prune_contents`：

- 候选条件：`status IN ('completed','failed','interrupted')` **且** `finished_at IS NOT NULL
  AND finished_at < now - ONCALL_RUN_CONTENT_RETENTION_DAYS` **且** `content_pruned_at IS NULL`
  **且**（`input != ''` 或 `output IS NOT NULL`）。
- 一次最多 `ONCALL_RETENTION_BATCH` 场，`SELECT ... FOR UPDATE SKIP LOCKED`，同一事务内
  `UPDATE runs SET input = '', output = NULL, content_pruned_at = now()`。
- `input` 是 `NOT NULL` 列：清理写**空串**而不是改约束。空串与「本来就空」的区分靠
  `content_pruned_at`；而正常输入不可能是空串（`ChatRequest.message` 是 `min_length=1`），
  所以空串只可能来自清理。
- 非终态 run 永远不清：挂起审批的 run 可能几周没有新事件，正文是审批上下文。
- 部分索引 `idx_runs_content_retention (finished_at) WHERE content_pruned_at IS NULL`：
  事件先清，清完的行会掉出 `idx_runs_retention`，正文清理**不能复用**那个索引，否则每轮
  从最老的行开始扫、越过整个历史。

### 2. 保留摘要：不删行，也不删引用快照

清理后 `runs` 仍是一行完整的摘要：`status` / `intent` / `model` / `step_count` /
`token_*` / `cost_cents` / `error_code` / `failure_category` / `started_at` / `finished_at` /
`events_pruned_at` / `cited_document_ids`。

- 运行列表、失败率、成本看板与 `model_calls` 对账都靠这些列，删行等于把观测口径一起删了。
- `cited_document_ids` 是元数据（至多 50 个 id），不含正文；留着它，详情页仍能解释
  「这场 run 引用过什么」，也避免清理与 ADR-0022 的读时校验相互干扰。
- `approvals` 的治理证据不受影响。

### 3. 配置强制：正文保留期不得短于事件保留期

`Settings` 在启动期拒绝 `ONCALL_RUN_CONTENT_RETENTION_DAYS < ONCALL_EVENT_RETENTION_DAYS`：

- 事件里是同一段回答正文（`message.delta` / `message.completed.text`）。正文 90 天、
  事件 180 天，等于删了 `runs` 却把正文留在事件表里，还让它继续被回放。
- 所以两个开关只能「正文 >= 事件」：想早点删正文，就同时把事件保留期调小——那是一次
  明确的合规决定，而不是一个静默的配置副作用。
- 默认两者都是 180 天，与 docs/09 §9 的审计 180 天对齐。

### 4. 读路径：过期优先于权限，且不可恢复

| 路径 | 表现 |
|---|---|
| `GET /runs/{id}` | `input: ""`、`output: null`、`content_pruned_at` 非空；状态/计量/失败归因照常 |
| `GET /runs/{id}/events` | 不变：事件早已按 ADR-0021 清掉，仍 `200` + `events: []`，且 `content_redacted: false`；读路径一次查询同时取引用快照与过期标记，不额外加往返 |
| `POST /chat/stream`（幂等重放） | `410 CONTENT_EXPIRED`，不建 SSE——不流一个「成功但没有回答」的空流 |
| `recent_turns()` | 不额外过滤：多轮历史只认 `output` 非空，清空后那一轮自然消失 |
| `content_is_redacted()` | 直接返回 `false` 并跳过知识库查询：正文已经不存在，谈不上「按你的权限隐藏」 |

- **过期优先于权限**：两种原因同时成立时详情页说过期。否则用户会读到一个错误的提示
  （「可见范围恢复后内容自动恢复」），而实际是永久删除。
- 详情接口多一个「是否已清理」的判断就够，不需要额外查询：`content_pruned_at` 在
  `runs` 上，详情本来就取整行。

### 5. 顺序与幂等

清理任务每轮固定「事件 → 正文 → 计量」：

- 正文在事件之后清，保证**正文不会比事件活得更久**（同一轮内多副本也只是先后差一次事务）。
- 两个标记写入后都不会再被选中，重复执行是空操作；`dry-run` 只预览第一批（不写标记时
  循环会把同一批候选重复计数，与 ADR-0021 一致）。
- 跑满批次上限时仍记 `retention_backlog_remaining`，CLI 输出新增
  `content_before` / `content_runs`。

## 后果

- **不可逆**：正文清空后只能靠数据库备份恢复；文档与运维手册都写明这一点，前端提示
  不能写「恢复可见范围后自动恢复」（那是 ADR-0022 的语义）。
- 多轮上下文会丢轮次：超过正文保留期的会话历史不再进上下文。这是「只留摘要」的预期。
- 详情页的问题会显示为空，必须靠 `content_pruned_at` 解释；只用 `input` 判断会把
  「过期清理」误读成「用户发了空消息」。
- 两个保留期形成约束：想更早删正文就要连事件保留期一起降，现场需要理解这个顺序。
- **升级时要一起改配置**：现场若把 `ONCALL_EVENT_RETENTION_DAYS` 调到 180 天以上
  （例如审计要求 365 天），必须同时把 `ONCALL_RUN_CONTENT_RETENTION_DAYS` 调到不短于它，
  否则启动期直接拒绝——这是有意的：默认 180 会让正文比事件早删 185 天，事件里还留着
  同一段正文。
- 存量数据：迁移只加列，不回填；升级后第一轮清理按 `finished_at` 处理过期 run。
- 没有性能基准：每轮多一次 `SELECT ... FOR UPDATE SKIP LOCKED` + 一次 `UPDATE`，
  与 ADR-0021 同样没有在真实体量上量过（见「待定」）。
- 与 ADR-0022 共存：权限回收是读时的、可恢复的；时间清理是写时的、不可恢复的。两者
  都覆盖详情/事件/重放/多轮历史，但**只有权限回收会随可见性恢复**。

## 验证

- `tests/test_retention.py`：到期清空正文、未到期不动、非终态不清、dry-run 只预览、
  幂等（标记写入后不再入选）、正文可长于事件（事件先失效、正文仍在）、正文清空后
  `recent_turns` 为空、只剩正文积压时单轮继续排空、阈值来自配置。
- `tests/test_store_contract.py` 新增 `_exercise_prune_contents`：内存与 Postgres 共用同一组
  断言（未到期不动、dry-run 只列候选、清空后 `input == ""`/`output is None`/标记有值、
  摘要与列表仍可读、历史剔除该轮、重复清理不再选中）。
- `tests/test_runs_api.py`：详情只留摘要（`input` 空串、`output: null`、`content_redacted: false`）、
  列表带 `content_pruned_at`、事件为空、引用文档随后被收权时仍说过期而不是不可见。
- `tests/test_chat_stream.py`：幂等重放返回 `410 CONTENT_EXPIRED`；正文清理后追问不再带上
  上一轮历史（回到拒答）。
- `tests/test_runs_content.py`：正文已清空时 `content_is_redacted` 恒为 false。
- `tests/test_config.py`：`ONCALL_RUN_CONTENT_RETENTION_DAYS` 配 0 拒绝；小于事件保留期拒绝；
  事件保留期调大到 365 天、正文保留期仍是默认 180 时也拒绝（升级场景，不是静默延长正文的
  删除时间）；默认两者都是 180。
- 迁移 0012 已 `downgrade → upgrade` 往返，`alembic check` 无漂移；开发库上
  `python -m app.cli prune --dry-run` 输出含 `content_before` / `content_runs`。
- 完整回归：默认 **330 passed + 24 skipped**；带 Postgres **354 passed**；前端 **56 tests**、
  `tsc` / `oxlint` / `oxfmt` / `pnpm build` 全绿；`ruff` / `ruff format --check` / `mypy` 通过。

## 待定

- 事件冷归档（对象存储 / 归档表）：满足「超过 180 天仍要能看」的现场
- 审批记录（`approvals` / `approval_grants`）的保留期
- 按用户 / 租户差异化的正文保留期（当前是全局一个值）
- 清理任务的性能基线：单批耗时、对 Postgres autovacuum 的影响
