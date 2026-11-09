# ADR-0013 · 自研薄模型网关

- 状态：已采纳（W4 D16–D18）
- 日期：2026-11-09
- 相关：docs/01 §2、docs/02 §2.4、docs/03 §2、docs/04 §3/§6、docs/10 W4

## 背景

W1–W3 的 8 节点里只有 plan 需要模型（classify 是规则兜底），但一旦接入模型，
必须同时回答四个问题：

1. 哪类请求走小模型、哪类走大模型（不能把路由丢给模型自己）
2. 云端不可用时能不能切到本地（私有化场景没有公网）
3. 每次调用花了多少 token / 多少钱，run 失败或中断时账还对得上吗
4. 超预算时是返回 500、静默截断，还是在调用前拒绝

这些正是项目要展示的设计，因此不能用一个黑盒网关把决策配置化掉。

## 选项

| 方案 | 优点 | 代价 |
|---|---|---|
| A. LiteLLM / OpenRouter 一类聚合 SDK | 接入快，provider 多 | 路由/降级/预算被配置化，讲不清「为什么这样选」；依赖体积与版本风险 |
| B. 直接用 OpenAI SDK | 简单 | Ollama 走另一套协议；计量、失败切换、预算仍要自己写，等于半个网关 |
| C. 自研薄层（**采纳**） | 路由/降级/计量/预算全部可测可讲；只依赖 `httpx` | 代码量约 500 行；新 provider 要自己适配 |

## 决策

### 1. 协议与适配

- `OpenAICompatibleProvider`：`POST {base_url}/chat/completions`，覆盖云端、vLLM
- `OllamaProvider`：`POST {root}/api/chat`（`base_url` 配成 `.../v1` 会自动去掉），
  支持原生 `format=json`
- 不引入 provider SDK：两种协议都只是 JSON + Bearer，`httpx` 足够；少一层依赖，
  也避免 SDK 把重试/超时策略藏在内部

### 2. 路由是规则，不是模型

| purpose | 首选 | 原因 |
|---|---|---|
| `classify` | local | 只做三分类，小模型足够；延迟/成本敏感 |
| `plan` | cloud 优先，回落 local | 需要跨领域关联与稳定 JSON，云端质量更好；私有化时用本地 |
| `answer` | 同 plan | 当前 finalize 仍是确定性抽取，预留 |

`ONCALL_MODEL_PROVIDERS` 只决定启用哪些 provider，不改变优先序；`options.model`
只能路由到已配置的模型，未知模型名忽略，避免客户端指定任意模型。

### 3. 失败切换

按路由顺序逐个尝试；超时/5xx/429/网络错误都进入下一个 provider。每次失败尝试
写一行 `model_calls(status=error, token=0)`，成功切换的那一行写 `status=fallback`。
全部失败时：

- classify：退回规则，run 继续
- plan：退回规则计划（`plan_source=fallback`），run 继续
- 计量写入失败：不降级，`run.failed(MODEL_ERROR)` —— 没有计量行的 token 不可接受

### 4. 计量是预算的前提

- `model_calls` 一行 = 一次真实 provider 调用
- 写计量行与 `runs.token_* / cost_cents` 的增量更新在**同一事务**里完成
- 不等到 `run.completed` 才结算：失败、超时、审批拒绝的 run 也必须对账
- 成本 = `ceil((token_in * price_in + token_out * price_out) / 1e6)`，单位分；
  单价 > 0 且产生 token 时至少 1 分
- 一致性断言：`runs.token_in == sum(model_calls.token_in)`，
  `tests/test_metrics_pg.py` 覆盖失败 run

### 5. 预算与限流

- 限流：按用户滑动窗口（Redis ZSET），默认 30 次/分钟；超限在**建 run 之前** 429
- 预算：单 run `ONCALL_RUN_BUDGET_CENTS`（默认 50 分）+ 当日
  `ONCALL_DAILY_BUDGET_CNY`（默认 5 元，按 UTC 日）
- 调用前按估算预扣（Redis Lua 原子），返回后按实际结算；估算超限直接拒绝，
  不会先花钱再报错
- Redis 不可用时退化为进程内实现并打 warning：限流/预算只在单实例生效，
  但聊天接口不能因此 500

### 6. mock 模式

`ONCALL_MOCK_MODE=true`（默认）时完全不构建网关，classify/plan 走确定性规则，
`model_calls` 为空、成本为 0。目的：

- 无 key、无 Ollama 也能完整演示三条剧本（W6 D28）
- 评测 v0 的指标只衡量规则 + 检索，不把「模型随机性」混进基线

代价：默认路径不覆盖网关；真实模型效果与成本需要显式设置
`ONCALL_MOCK_MODE=false` 并配置 provider 后另跑一轮（docs/08 §6）。

## 后果

- 新增 `gateway/` 约 600 行 + `core/limits.py` 约 250 行；测试覆盖路由、计价、
  failover、预算、计量一致性
- `classify` / `plan` 变成 async；节点仍不发事件、不直接 HTTP（R5）
- plan 的模型输出必须过 `validate_args`，身份字段由服务端注入（R9）；
  模糊输入不能升级成写操作（R10）
- 真实模型的分类准确率（D11 的 50 条标注集）仍未测，记入后续里程碑；
  `query_cmdb` 仍是内置假数据

## 待定

- 是否在 W5 加 token 级流式（当前非流式，`first_token_ms` 恒为 NULL）
- 是否把「按租户/按用户」日预算做成表，而不是只有全局日预算
- bge-reranker / 更强本地模型接入后，是否调整 `plan` 的 cloud 优先策略
