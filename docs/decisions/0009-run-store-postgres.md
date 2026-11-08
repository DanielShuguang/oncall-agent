# 0009 · 运行态存储：Postgres + 事件投影

- 日期：2026-11-08
- 状态：已采纳（W1 D4）
- 相关：`docs/02-data-model.md`、`docs/03-api-contract.md`、`server/app/core/store.py`

## 背景

W1 D3 用内存 store 先把「事件 → SSE → 前端 reducer → 补拉」跑通，但进程重启就丢数据，
`Last-Event-ID` 续传也就无从谈起。D4 要把 `runs` / `run_events` 落到 Postgres，并保证：

- 事件先落库再推送（R2），推送失败不丢数据
- 单 run 内 `seq` 从 1 严格递增，并发追加不能撞主键（R7）
- 客户端重复提交（`client_msg_id`）不重复执行
- 前端断开后能补拉；服务端要能说出 run 停在哪

## 方案对比

| 方案 | 优点 | 代价 / 否决理由 |
|---|---|---|
| A. 只写 `run_events`，`runs` 每次现算 | 单一真相源，不会不一致 | 详情/列表每次扫事件表，W4 成本看板还要 join；无法按 status 建索引 |
| B. `run_events` + `runs` 投影（**采纳**） | 读路径一条 SQL；投影规则集中；仍可回放校验 | 写事件时多一次 UPDATE，需保证同事务 |
| C. Redis Stream 存事件，定时刷 PG | 写入快 | 多一个真相源；私有化部署多一个组件；崩溃窗口内事件丢失 |
| D. 内存 + 定期快照 | 改动最小 | 仍会丢最近一段；无法跨副本；不能用于演示之后的环境 |

## 决策

1. **Postgres 是默认实现**（`ONCALL_STORE_BACKEND=postgres`）。内存实现只保留给测试与
   显式 `memory` 模式，**不做静默降级**：库挂了要 503 / degraded，不能悄悄写内存。
2. **事件与投影同事务**：`append()` 内先锁 `runs` 行（`FOR UPDATE`），再取 `MAX(seq)+1`、
   插入 `run_events`、更新 `runs` 汇总字段，一次 commit。一个 run 只有一条写入流，
   行锁的串行成本可忽略，比给每个 run 建序列简单。
3. **投影规则集中**在 `core/store.py: build_run_patch`，只做机械映射（文档表见 `docs/02` §3.1）。
   审批语义、重试等业务判断仍留在 runtime（W3），store 不替它做决定。
4. **建流前失败返回 503**；进入流之后的 DB 故障只记日志并截断，客户端靠补拉恢复
   （「能建流就 200」的边界）。
5. **幂等**：`client_msg_id` 唯一约束兜底；命中时只回放已落库事件，不重跑 Agent。
6. **SQLAlchemy 模型与迁移同源**：`alembic check` 进 CI，防止「模型改了、迁移忘了」。

## 后果

- 每次事件一次事务；当前演示量级（每 run 几十条）完全够用。若将来单个 run 事件上千，
  再考虑批量写或异步队列，但**不能牺牲「先落库再推送」**。
- 前端补拉依赖 `after_seq` / `Last-Event-ID`；`GET /runs` 列表分页仍留到 W4 D19
  （详情与补拉先满足 W1 验收）。
- 测试分两层：内存契约测试每次跑，Postgres 契约测试靠 `ONCALL_TEST_DATABASE_URL`
  接入真库（含并发追加用例）；CI 起 pgvector 服务并执行迁移。
- 内存实现与 PG 实现的接口由 `RunStore` Protocol 约束，换实现不影响 `api/`。

## 被否决的细节

- **用时间戳排序代替 seq**：同毫秒事件会乱序，且无法做「断点续传」的严格大于比较。
- **在 `api/` 里拼 SQL / 管事务**：违反 R4，换传输层时会重复实现。
- **依赖数据库默认值生成 `status`**：状态是事件投影的结果，默认值会掩盖「事件没写成功」。
