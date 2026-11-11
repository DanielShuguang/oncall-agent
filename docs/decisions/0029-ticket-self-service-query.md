# 0029 工单自助查询（`query_tickets`）

- 状态：已采纳
- 日期：2026-11-11
- 关联：[docs/06](../06-tool-governance.md)、[docs/04](../04-agent-design.md)、[ADR-0016](0016-approval-decision-transaction.md)、[ADR-0020](0020-multi-turn-context.md)

## 背景

`docs/06` §8.3 从 v1 起就列出了 `query_tickets`（读、2000ms、所有角色、查该用户历史工单），
但一直没注册，注记的理由是「随接真实系统时再加，避免先写假工具再改一遍治理用例」。
现在这个理由已经不成立：

- `tickets` 表从 W3 D14 起就是真实落库（审批通过后由 `create_ticket` 写入，ADR-0016），
  不是进程内假数据，只读查询没有「假工具」问题；
- 用户最高频的三个问题之一是「我的工单到哪了」，此前只能走知识库检索（检索到的
  是「如何报修」），或者被迫重新开一张单；
- `classify` 的写关键词包含「报修」，导致「我报修的打印机修好了吗」被误判成新的写操作，
  会再开一张单。这是本次顺带修掉的真实缺陷。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 只登记工具，完全交给模型选 | 否决 | mock 模式与模型降级路径只用规则计划，演示/离线环境永远用不上；写关键词误判也还在 |
| 新增 `ticket_query` 意图 | 否决 | 三意图是 `docs/03` / `docs/04` 与 50 条分类评测的契约，新增意图要同步提示词、混淆矩阵、前端展示，收益只是分类更「纯」 |
| 允许按任意 requester 查 | 否决 | 越权；身份只能来自服务端 token（R9） |
| 新建查询表 / 迁移 | 否决 | `tickets` 已有 `requester` / `status` / `created_at`，只读查询不需要新结构 |
| **登记只读工具 + 关键词规则计划 + 明确写操作优先** | **采纳** | 不扩意图契约，mock 与真实模式都能用；把「问进度」和「要开单」分开 |

## 决策

1. **工具契约**：`query_tickets(status?, limit?)`，读、2000ms、`roles=()`、`inject_identity=True`。
   `status` ∈ `open|in_progress|resolved|closed`；`limit` 1–20（默认 5）。
   schema `additionalProperties: false`，`requester` 不在 schema；模型若把身份字段塞进 args，
   由 `ToolGuard` 的 `RESERVED_ARGS` 直接拒绝（R9）。
2. **只能查自己**：handler 用 `Identity.user_id`，仓储方法
   `list_for_requester(requester, status=..., limit=...)` 在 SQL/过滤层就带
   `requester = :me`，按 `created_at DESC, id DESC` 取前 N 条。查询别人的工单没有参数入口。
3. **不新增意图**：`wants_ticket_status` 命中「我的工单 / 工单进度 / 报修进度 / 处理到哪 /
   修好了吗」等说法，且没有明确开单动作（`开单` / `帮我申请` / `提交申请` / `申请开通` /
   `帮我报修` / `要报修`）时，`classify_intent` 落 `knowledge`；`needs_model` 也排除这类
   确定性问法，分类阶段不再花一次模型调用（真实模式的 `plan` 仍会调一次模型，规则计划只是
   兜底）。过去时的「开单了 / 开过单 / 开单后」不算开单动作；反过来，状态句里出现
   「要报修 / 需要报修 / 想报修」仍按写操作走。三意图契约保持不变。
4. **规则计划补一条**：`rule_plan` 在写操作分支之后加 `query_tickets`，保证 mock 模式、
   模型不可用与项目演示都能用；真实模式下工具已注册，模型可直接选。
5. **回答以工单表为准**：`finalize` 检测到 `query_tickets` 结果时直接拼回答
   （有工单 → 单号/状态/优先级/标题/日期；空 → 「没有查到工单」；失败 → 「暂时没查到」），
   不再拼知识库步骤、不产生引用、不落「知识库没有检索到」的拒答。用户问的是自己那张单，
   检索到的流程文档是噪声。状态在回答里映射为中文（待处理/处理中/已解决/已关闭）。
6. **写操作优先级**：`我报修的…` 这类过去时不再触发 `create_ticket`；带「开单 / 帮我申请 /
   提交申请 / 申请开通 / 帮我报修」的请求仍优先按写操作处理（R10），不会被状态关键词抢走。
7. **数据面**：`_ticket_dict` 增加 `created_at` / `resolved_at`（ISO-8601），工具结果直接可读；
   两列在 `tickets` 表里本来就有，**无需迁移**。`requester` 暂不加索引——当前表量与
   「按人取最近 5 条」的访问模式不值得；工单量上来后再按真实查询计划补（见「待定」）。

## 后果

- 「我的工单到哪了」在 mock 模式与真实模式下都能得到基于工单表的回答，不再误开单。
- 工具是只读的，不走审批；`admin` 的工具开关/角色矩阵照常生效（`roles=()` 表示所有登录用户）。
- 组合问题（同一句既问资产又问工单）会以资产前缀 + 工单列表作答，不再给知识库步骤；
  这是有意的取舍，避免用「如何报修」的流程文档回答「我这张单到哪了」。
- 规则关键词仍有误伤面：例如「报修进度怎么查」会被当作查自己的工单。当前接受，
  在「待定」里记录；若真实流量里占比高，再考虑加政策问法排除或正式意图。
- `query_tickets` 结果照常进 `tool.result` 事件与前端 ToolCard（通用 JSON），回答正文由
  `finalize` 拼装；事件契约不变。

## 验证

- 后端默认：`uv run pytest -p no:warnings` → **413 passed, 31 skipped**（改前 402 + 30）。
- 真实 Postgres（pgserver 临时实例）：**441 passed, 3 skipped**（改前 429 + 3）；
  跳过的 3 条都是 Redis 账本/快照用例（本机未启动 Redis）。
- 新增测试：
  - `server/tests/test_tickets.py`：只返回本人、按创建时间倒序、limit、状态过滤；
  - `server/tests/test_tickets_pg.py`：真实 PG 上的本人过滤/排序/limit/状态过滤（默认跳过）；
  - `server/tests/test_tools_guard.py`：`query_tickets` 只返回调用者工单、伪造 `requester` 被拒；
  - `server/tests/test_agent_graph.py`：状态问法不触发写意图、规则计划选 `query_tickets`、
    finalize 有/空/失败三条路径。
- `ruff check` / `ruff format --check`（166 files）/ `mypy app`（103 files）通过。
- 分类评测：`uv run python -m app.eval.classify` → **50/50，joint 100%**（规则改动未影响标注集）。
- 前端未改：`tsc --noEmit`、`vitest` 60/60、`oxlint` 0/0、`oxfmt --check` 仍通过。
- 检索 / 提示词 / 多轮历史未改，未重跑 RAG 与多轮评测。

## 待定

- 工单详情（描述、受理人、解决时间）与分页/时间范围查询；本版只回答「最近 5 张的摘要」。
- IT 支持查他人工单需要新的权限模型（按组/按队列），不能只靠 `roles` 粗粒度。
- 状态中文映射目前写死在 `finalize`；若其他端也要展示，应下沉到 API/展示层统一。
- `requester` 索引与大数据量分页；等有真实工单量或慢查询证据再加。
- 规则误伤（「报修进度怎么查」这类政策问法）是否需要更细的排除，或升级为正式意图。
