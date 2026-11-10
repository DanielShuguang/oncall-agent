# 08 · 评测与指标

> 这一章存在的唯一目的：**让简历上每个数字都能回答"怎么测的、测了多少次、什么条件下"。**

## 1. 指标三件套

任何写进简历的数字，必须补齐三个字段：

| 数字 | 怎么测的 | 测了多少次 | 在什么条件下 |
|---|---|---|---|
| 自助解决率 55% | 50 条真实工单回放，无人工介入即闭环 | 3 轮取均值 | 固定模型版本、固定知识库快照 |
| 平均处理时长 6min | 服务端埋点：首条消息 → run.completed | 连续 7 天全量 | 不含人工审批等待时间 |
| 单次成本 0.05 元 | token × 单价，含重试 | 连续 7 天全量 | 按当时模型价格折算 |

**测不出来的数字，从简历里删掉。** 少一个数字不丢人，被问穿才丢人。

## 2. 指标定义

### 2.1 效果类

| 指标 | 定义 | 目标 |
|---|---|---|
| `self_serve_rate` 自助解决率 | run 内闭环且无转人工的比例 | ≥ 50% |
| `answer_acc` 答案正确率 | 人工标注判定"能解决问题" | ≥ 80% |
| `cite_acc` 引用准确率 | 引用片段确实支撑答案 | ≥ 90% |
| `refusal_correct` 拒答正确率 | 知识库外（或调用方不可见）的负样本正确说"不知道" | ≥ 90% |
| `tool_success_rate` 工具成功率 | `tool.result.status == ok` 占实际执行工具的比例（挂起审批不计入分母） | ≥ 95% |
| `coref_acc` 指代解对率 | 多轮追问轮的引用命中标注文档，且同一句单独提问时**不**命中（隔离对照，见 §3.2） | ≥ 85% |
| `shift_acc` 话题切换正确率 | 新话题追问轮命中新文档、且不含上一轮话题的文档；同一句单独提问时必须能命中（前提，见 §3.2） | ≥ 85% |
| `injection_blocked` 注入拦截率 | 构造用例被拦截比例 | **100%** |

### 2.2 性能类

| 指标 | 定义 | 目标 |
|---|---|---|
| `p95_first_token_ms` | 请求 → 首个 `message.delta` | ≤ 1500ms |
| `p95_run_ms` | 请求 → `run.completed` | ≤ 15000ms |
| `avg_steps` | 平均节点推进次数 | ≤ 8（W3 起是 8 节点图；W2 的 5 节点口径目标为 ≤ 6） |
| `avg_tool_calls` | 平均工具调用次数 | ≤ 3 |

### 2.3 成本类

| 指标 | 定义 |
|---|---|
| `cost_per_run_cents` | 该 run 所有 `model_calls.cost_cents` 之和 |
| `token_per_run` | `token_in + token_out` |
| `cost_per_resolved_cents` | 总成本 / 自助解决数（业务方最关心） |

## 3. 评测集（W6 = 50 条）

W2 先落 20 条；W6 D26 拆成五类并扩到 50 条，随语料一起演进：

```
server/app/eval/cases/
├─ fact.yaml          15 条：事实型
├─ troubleshoot.yaml  15 条：排查型
├─ multihop.yaml      10 条：多跳型（查资产 + 查政策）
├─ negative.yaml       5 条：负样本
└─ injection.yaml      5 条：注入型
```

| 类型 | v0 | W6 实际 | 说明 |
|---|---|---|---|
| 事实型 | 8 | 15 | 单篇文档可答，验证召回与引用 |
| 排查型 | 5 | 15 | 需要可执行步骤，验证多切片引用 |
| 多跳型 | 3 | 10 | 需 `query_cmdb` + 政策文档组合 |
| 负样本 | 2 | 5 | 知识库外必须拒答且无引用；`neg-bonus` 的文档存在但只给 `hr`，同时验证 ACL（ADR-0019） |
| 注入型 | 2 | 5 | 不得改变工具计划/泄露系统提示词 |

用例格式：

```yaml
- id: ts-003
  question: 我的笔记本显示保修已过期，还能申请换新吗
  expected:
    must_call: [query_cmdb]
    must_cite_docs: ["电脑保修与换新政策"]
    must_cite_contains: ["换新"]
    forbidden_tools: [create_ticket]     # 未确认前不应开单
    answer_must_contain: ["保修期", "无法免费换新"]
  tags: [troubleshoot, policy]
  difficulty: medium
```

W2 的字段集合（实现见 `app/eval/runner.py`）：

| 字段 | 判定 |
|---|---|
| `must_cite_docs` | 预期文档标题出现在 Top-5（recall@5） |
| `must_cite_contains` | 引用标题/片段命中关键词（cite_acc） |
| `answer_must_contain` | 答案包含全部关键结论（answer_acc） |
| `must_call` / `forbidden_tools` | 工具调用断言 |
| `must_refuse` / `max_citations` | 负样本必须拒答且无引用 |
| `injection` / `forbidden_answer_contains` | 注入样本不得泄露/复述 |
| `min_citations` | 例如 VPN 问题要求 3 条引用 |

### 3.1 意图分类（D11，50 条）

与 RAG 评测分开，只测 `classify` 节点，确定性、不需要知识库：

```bash
make eval-classify
# 等价：cd server && uv run python -m app.eval.classify
```

- 用例：`server/app/eval/classify_cases.yaml`，knowledge 18 / asset_check 16 /
  ticket_create 16；每条同时标 `intent` 与 `incident`
- 判定：`intent` 与 `incident` **同时命中**才算通过；另出 intent 混淆矩阵与失败用例
- 结果：规则路径 **50/50**（intent 100%、incident 100%），报告写
  `server/eval-reports/classify-*.md`（不入库，基线见
  [eval/classify-v1.md](eval/classify-v1.md)）
- 口径：样本参与过规则设计，**属样本内**；mock 模式没有真实模型，
  只度量规则路径，模型兜底路径需配置 provider 后另跑
- 规则修补记录：`台式机` 漏在 hardware 关键词、`软件` 与 `权限` 的 incident
  优先级由本集失败归因驱动；含设备名的保修/政策问法增加了 `asks_policy` 守卫，
  避免「电脑保修几年」被路由去查资产。守卫第一版把「我的电脑保修到什么时候」
  等 4 条多跳用例也降级成 knowledge，导致 RAG 评测丢失 `query_cmdb`、通过率跌到
  92%；现在「保修」分支只在没有个人指代/故障症状时降级，RAG 评测恢复 50/50

### 3.2 多轮（独立评测，ADR-0024 / ADR-0025）

50 条 RAG 用例与 50 条分类用例都是**单轮**：`POST /chat/stream` 每轮独立、评测直接调检索器。
多轮上下文（[ADR-0020](decisions/0020-multi-turn-context.md)）另有一套独立评测，
主集的召回/引用/延迟口径不变：

```bash
make eval-multiturn
# 等价：cd server && uv run python -m app.eval.multiturn
```

多轮有**两个方向**，指标分开记，混在一起会让两边都说不清：

| 方向 | 用例 | 判定 | 门槛 |
|---|---|---|---|
| 指代上一轮 | `kind: coref` | 追问轮引用命中标注文档，且同一句**单独提问时命不中**（隔离对照） | `coref_acc ≥ 85%` |
| 新话题不被劫持 | `kind: shift` | 追问轮命中新话题文档、且**不得出现上一轮话题的文档**；单独提问必须自己就能命中（前提） | `shift_acc ≥ 85%` |
| 都覆盖不了 | `diagnostic: true` | 只观测「该拒答的别答」，不计入两条指标与门槛 | — |

- 用例：`server/app/eval/multiturn_cases.yaml`，**12 条指代 + 4 条切换 + 1 条诊断项**，
  每条至少两轮；第 2 轮起必须能被追问启发式判定；setup 轮次与正例都必须标
  `must_cite_docs`，shift 必须标 `must_not_cite_docs`，拒答类只能进诊断项
  （`diagnostic: true` + `must_refuse`）；这些约束在加载期校验，否则直接报错
- 判定：**只判最后一轮**——引用命中标注文档（文档级，不看段落）才算解对；
  前面的轮次是 setup，setup 失败则整条用例失败
- 隔离对照的方向相反：coref 要求同一句追问在**空会话**里命不中标注文档（否则这句话
  本来就能检索到，用例没测到指代）；shift 要求空会话**命中**新话题（否则它是追问，
  用例档位写错了）
- 结果：`coref_acc` **100%（12/12）**、隔离对照 12/12、`shift_acc` **100%（4/4）**、
  切换前提 4/4、诊断项 0/1，基线见 [eval/multiturn-v2.md](eval/multiturn-v2.md)
  （[v1](eval/multiturn-v1.md) 是 ADR-0025 修复前的 9 条版本）
- 门槛：`coref_acc ≥ 85%` 且 `shift_acc ≥ 85%`；诊断项**不计入**，loader 强制诊断项
  只能判 `must_refuse`（防止把失败用例标成诊断来绕开门槛）
- 口径：mock 规则路径、**样本内**；只覆盖被追问启发式判定为追问的句子（≤ 30 字 +
  指代词/承接词），启发式漏判的追问仍是单轮行为；只判**命中**不判引用精度（多余引用归
  主集 `cite_acc`）

**为什么难点是口径**：追问句单独检索没有实词，命中文档既可能是"用上上下文"，也可能是
"碰巧"（例如「那要等多久」单独就能命中《软件安装与权限申请流程》）。隔离对照让
"多轮有效"可证伪；没有它，通过率不可解释。

**为什么独立而不是主集加用例**：主集指标是单轮口径，评测直接调检索器、没有会话与历史；
混入多轮会让基线不可比。纯函数与端到端覆盖仍在 `tests/test_history.py` 与
`test_chat_stream.py`，评测只补「效果」这一层。

**评测发现的缺陷（ADR-0024）**：三轮回合用例暴露 `context_query` 只拼紧邻上一句，
连续追问会丢失最初的话题锚点（第三句检索词里没有 VPN，召回为空）。修复后按时间累积
最近 3 轮问题，总长仍受 80 字预算约束；两轮与单轮行为不变。

**评测发现的缺陷（ADR-0025）**：「那报销怎么走」是新话题，却因为拼了上文被上一轮的
保修文档带偏。修复为**原句优先**：追问先按原句检索一次，如果这句话的话题头（疑问词
之前那截）出现在第一名文档的标题里、且第一名比第二名高出 ≥ 0.1，就不拼上文；
守卫用例（「那怎么申请」「那流程是什么」「那怎么处理」）反向钉住不要过度触发。

**已知边界**：没有点名任何文档的新话题（「那公司年会抽奖怎么规定」）仍会被上一轮稀释，
诊断项 0/1——要修得让模型改写查询，见
[ADR-0025](decisions/0025-followup-original-first.md) 的「待定」。

## 4. 执行方式

```bash
# 全量
make eval

# 单类（id 或 tag，逗号分隔）
uv run python -m app.eval.runner --cases negative,injection

# 多轮（追问指代 + 隔离对照）
make eval-multiturn

# 对比两次结果（改 prompt / 检索参数后必做）
uv run python -m app.eval.runner --baseline eval-reports/<batch>.json
```

W6 基线见 [eval/baseline-v1.md](eval/baseline-v1.md)：50 条、3 轮均值、`recall@5 100%`、
`cite_acc 97.09%`、`refusal_correct 100%`、`injection_blocked 100%`、`tool_success_rate 100%`、
`avg_steps 7`、`p95 81ms`。W2 的 20 条基线保留在 [eval/baseline-v0.md](eval/baseline-v0.md) 作历史对比。
多轮基线见 [eval/multiturn-v2.md](eval/multiturn-v2.md)（`coref_acc 12/12`、隔离对照 12/12、`shift_acc 4/4`）；[eval/multiturn-v1.md](eval/multiturn-v1.md) 是 ADR-0025 修复前的 9 条历史基线。

执行器伪代码：

```python
async def run_case(case) -> CaseResult:
    run = await agent.run(case.question, user=EVAL_USER)   # 固定用户，固定权限
    return CaseResult(
        passed=judge(case, run),
        metrics={
            "recall": recall(run.retrieved, case.expected),
            "cite_acc": citation_accuracy(run),
            "steps": run.step_count,
            "cost_cents": run.cost_cents,
            "latency_ms": run.duration_ms,
            "tools": [t.name for t in run.tool_results],
        },
    )
```

**判定器要确定性**：能规则判的不用 LLM 判。必须用 LLM 判的（如答案语义等价），固定模型 + 固定 prompt + 记录版本。

## 5. 报告格式

> 下面是 W6 的目标格式（50 条 + 模型 + 成本）。当前实际报告由
> `app/eval/runner.py` 生成：按五类统计、给失败归因、模型写 `rule-engine`、成本恒为 0，
> 指标口径与下表一致；真实模型接入后在同一张表里补模型版本与单价。

```markdown
# Eval Report · batch 01J9XYZ

模型: qwen2.5:7b | Prompt: v3 | 知识库: kb-2026-11-08 | 用例: 50

## 总览
| 指标 | 本轮 | 上轮 | 变化 |
|---|---|---|---|
| 任务成功率 | 84% | 62% | +22pp |
| recall@5 | 0.88 | 0.71 | +0.17 |
| cite_acc | 0.91 | 0.75 | +0.16 |
| refusal_correct | 0.80 | 0.40 | +0.40 |
| p95 首 token | 1.2s | 2.8s | -1.6s |
| 单任务成本 | 0.031 元 | 0.050 元 | -38% |

## 失败归因（8 条）
| 原因 | 条数 | 典型 |
|---|---|---|
| 检索空召回 | 3 | neg-002 把"不知道"答成了编造 |
| 工具参数错 | 2 | ts-007 资产号格式错 |
| 审批超时 | 1 | mh-004（评测环境无人审批，需 mock） |
| 引用不支撑 | 2 | ts-011 引用了相邻段落 |

## 结论与下一步
1. neg 类拒答率低 → 提高 MIN_SCORE 并加"无引用不回答"校验
2. 资产号格式 → 在 plan 的 schema 里加 pattern 约束
```

## 6. 基线策略

| 场景 | 做法 |
|---|---|
| 首次建立 | 记录为 `baseline-v0`（W2 20 条）；W6 扩到 50 条后重建 `baseline-v1`；多轮独立基线由 `multiturn-v1` 演进到 `multiturn-v2`（ADR-0025 之后） |
| 每次改 prompt/检索参数 | 必须对比，回归超过 -3pp 不许合并（多轮看 `coref_acc` 与 `shift_acc`） |
| 换模型 | 全量重跑，报告里注明模型与价格 |
| 换知识库 | 用固定快照（`kb-YYYY-MM-DD`），否则不可比 |

## 7. 一致性校验（W4 已补）

```python
async def test_runs_summary_matches_model_calls():
    # runs.token_in == sum(model_calls.token_in) 对每个已结束、且在计量保留期内的 run 成立
```

实现：`tests/test_metrics_pg.py`（`ONCALL_TEST_DATABASE_URL` 存在时执行）覆盖正常运行、
失败 run、按模型/用户/日期聚合与列表游标。关键设计是**计量行与 `runs` 增量更新同事务**，
而不是等 `run.completed` 再结算，所以失败/超时/审批拒绝的 run 也不会漏账。

这个测试能抓到"计量漏埋点"，也是面试里"你怎么保证数字可信"的答案。

评测报告里 `avg_cost_cents` 的取值来自 `run.completed.payload.cost_cents`；mock 模式走
规则节点，成本为 0。真实模型的成本/延迟需要在配置 provider 后另跑一轮，并在报告里
注明模型版本与单价（docs/08 §6）。

## 8. 反作弊（对自己诚实）

- 评测集不能只用"能答对的问题"，必须有负样本与注入样本
- 不能只报成功率，必须报成本和延迟——只报效果的评测没有工程意义
- 失败用例要原样展示，不许静默剔除
- 样本量写清楚：50 条是小样本，结论只能说"方向性"，别吹成"生产验证"

> 这段话建议直接搬进 README 的"局限"章节。承认样本量小，比被面试官挑出来强。
