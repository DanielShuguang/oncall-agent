# 0038 工单详情查询（`query_tickets` 按单号）

- 状态：已采纳
- 日期：2026-11-12
- 关联：[docs/06](../06-tool-governance.md)、[docs/04](../04-agent-design.md)、
  [ADR-0029](0029-ticket-self-service-query.md)、[ADR-0022](0022-run-content-visibility.md)

## 背景

ADR-0029 让用户能查「我最近的工单」，但回答只有单号、状态、优先级和标题。
用户从回答里拿到 `TCK-1A2B3C4D` 后追问「这张单什么情况」，智能体只能再列一遍
摘要；描述、处理人、创建/解决时间都在 `tickets` 表里，却没有入口。

`TicketRepository` 原来的 `get(ticket_id)` 不按 requester 过滤，是给审批恢复等
内部路径用的，不能直接暴露给工具：接了真实数据后，模型可以拿别人的单号试出
「这张单存在」。这次一并补上按身份过滤的单条查询。

分页、时间范围、按资产筛选仍不做：单用户工单量小，先补「看得到详情」这个洞。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 新增 `query_ticket_detail` 工具 | 否决 | 同一领域两个读工具，模型要多学一次选择；治理表、测试、降级都要写两遍 |
| 列表结果里直接带详情 | 否决 | 列表一次最多 20 条，每条带 500 字描述，事件与回答都会膨胀；列表视图也不需要详情 |
| 直接查 SQL / 在 API 里拼 | 否决 | 违反 R3（治理只在 registry）与 R4（API 不写业务、不写 SQL） |
| **复用 `query_tickets`，加可选 `ticket_id`** | **采纳** | 一个工具两种模式，schema 互斥；身份过滤放在仓储层；`finalize` 直接作答 |

## 决策

1. **一个工具、两个模式**：`query_tickets(ticket_id?, status?, limit?)`。
   传 `ticket_id` 走详情分支，返回 `{"ticket": {...} | null}`；不传走列表分支，
   返回 `{"tickets": [...], "count": n}`。两个分支互斥，`status` / `limit` 只在
   列表模式生效，schema 的 description 写明。
2. **身份过滤下沉到仓储**：`TicketRepository.get_for_requester(requester, ticket_id)`
   同时按 `id` 与 `requester` 查；不是本人的单返回 `None`，调用方无法区分
   「不存在」与「不是你的」。工具用 `identity.user_id`，model/plan 都传不了
   requester（R9）。
3. **空结果是合法结果**：`{"ticket": null}` 不是工具错误，不触发重试、不落
   `tool.failed`；只有数据库故障才让工具失败。回答统一说「你名下没有查到工单 X」，
   不猜是单号错还是权限问题。
4. **单号规范化**：`classify.ticket_id_from_query` 用
   `\b[Tt][Cc][Kk]-[0-9A-Fa-f]{8}\b` 从原句提取并转大写；工具再 `upper()` 一次。
   schema 的 pattern 同时接受大小写，模型传小写也能通过校验。
5. **意图与计划**：句子里出现具体单号即视为「查自己的单」，即使没有「进度」
   「到哪了」这类词；仍然保持 `knowledge` 意图（不新增 intent，不动 50 条分类
   评测），`needs_model` 排除，规则计划直接把单号放进 `args`。用户同时说「开单」
   与单号时仍按写操作优先（R10）。
6. **回答不拼知识库**：`finalize` 看到 `ticket` 字段就直接用表数据作答——
   单号、状态/优先级、标题、问题描述（截 200 字）、处理人（缺省「未分配」）、
   创建日期，有解决时间再加一行；不产生引用、不落「知识库没有检索到」的拒答。
   详情模式不列列表，列表模式仍只展示最近 5 张。`tool.result` 的 payload 不带 args，
   未找到时从 `state["plan"]` 取单号用于回显。
7. **无迁移**：`tickets` 表已有全部字段，`resolve`/`assignee` 由后续流程写入；
   本次只加查询路径。前端不改：工具结果仍由通用卡片渲染，回答正文已带详情。

## 后果

- 同一个工具返回两种 JSON 形状，调用方（finalize、测试、未来的 UI）必须按
  `"ticket" in result` 区分；已在 docstring 与 docs/06 写明。
- 详情只对本人开放，IT 支持仍不能查他人；按组/队列的权限模型另开 ADR。
- 描述可能包含用户自己写的敏感信息；当前只展示前 200 字，完整内容仍在库中，
  受 `tickets` 的保留策略约束（目前不清理）。
- 单号是 8 位十六进制，理论上可枚举；接口按 requester 过滤，枚举只能确认
  「自己名下没有」，不能探测他人是否存在。
- 列表与详情共用 2000ms 超时与同一套治理；没有新增环境变量。

## 验证

- 默认 `uv run pytest` **456 passed + 34 skipped**（19.96s）；新增
  `test_get_for_requester_is_scoped_and_missing_returns_none` 与
  `test_ticket_detail_query_by_ticket_id`（classify/plan/finalize 三路 + 未找到话术）。
- 真实 Postgres：`tests/test_tickets_pg.py` 的既有用例补 `get_for_requester`
  本人/他人/不存在断言，**487 passed + 3 skipped**（未新增 PG 测试函数）。
- `ruff check` 通过、`ruff format --check` 179 files、`mypy app` 106 files。
- 前端未改，仍 **65 tests / 13 files**；无迁移，`alembic` 不变；检索、提示词、
  多轮历史未改，未重跑 RAG/多轮评测。

## 待定

- 工单分页、时间范围、按资产/状态组合筛选；等真实工单量或慢查询证据再补。
- IT 支持查他人：需要按组/队列的权限模型，不能只靠 `roles`。
- 状态中文映射目前写死在 `finalize`；其他端也要展示时下沉到展示层。
- `requester` 列索引：单用户工单量小，暂不加。
- 详情字段是否要展示审批记录、处理轨迹、附件；这些数据还不存在，先不设计。
- 编辑/关闭工单是写操作，需另走审批与幂等设计，不在本次范围。
