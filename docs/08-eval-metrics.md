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
| `refusal_correct` 拒答正确率 | 知识库外的负样本正确说"不知道" | ≥ 90% |
| `tool_success_rate` 工具成功率 | `tool.result.status == ok` 占实际执行工具的比例（挂起审批不计入分母） | ≥ 95% |
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
| 负样本 | 2 | 5 | 知识库外必须拒答且无引用 |
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

## 4. 执行方式

```bash
# 全量
make eval

# 单类（id 或 tag，逗号分隔）
uv run python -m app.eval.runner --cases negative,injection

# 对比两次结果（改 prompt / 检索参数后必做）
uv run python -m app.eval.runner --baseline eval-reports/<batch>.json
```

W6 基线见 [eval/baseline-v1.md](eval/baseline-v1.md)：50 条、3 轮均值、`recall@5 100%`、
`cite_acc 97.09%`、`refusal_correct 100%`、`injection_blocked 100%`、`tool_success_rate 100%`、
`avg_steps 7`、`p95 81ms`。W2 的 20 条基线保留在 [eval/baseline-v0.md](eval/baseline-v0.md) 作历史对比。

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
| 首次建立 | 记录为 `baseline-v0` |
| 每次改 prompt/检索参数 | 必须对比，回归超过 -3pp 不许合并 |
| 换模型 | 全量重跑，报告里注明模型与价格 |
| 换知识库 | 用固定快照（`kb-YYYY-MM-DD`），否则不可比 |

## 7. 一致性校验（W4 已补）

```python
async def test_runs_summary_matches_model_calls():
    # runs.token_in == sum(model_calls.token_in) 对每个已结束的 run 成立
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
