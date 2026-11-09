# 10 · 6 周路线图

> 30 个工作日。每周留半天缓冲，不排满。**每周五必须能演示当周验收项**，演示不了就砍功能不延期。

## 总览

| 周 | 主题 | 周验收（必须能演示） |
|---|---|---|
| W1 | 地基 | 刷新页面能恢复到断点，事件顺序正确 |
| W2 | RAG | 问"VPN 连不上怎么办"，答案带 3 条可点击引用 |
| W3 | 工具治理 + 审批 | 三条剧本走通，越权用例被拦 |
| W4 | 网关 + 观测 | 任意对话能答"花了多少 token、多少钱、慢在哪步" |
| W5 | 前端打磨 + 后台 | 非技术同事能自己传文档、配工具、看审批 |
| W6 | 交付 | 陌生人按 README 30 分钟内跑起来 |

---

## W1 地基

| 天 | 任务 | 产出文件 | 验收 |
|---|---|---|---|
| D1 | 仓库 + uv + FastAPI 骨架 + docker compose + 健康检查 | `server/app/main.py`, `core/config.py`, `api/health.py` | `GET /api/health` 返回 db/redis 状态 |
| D2 | Pydantic 事件模型 + OpenAPI + `openapi-typescript` + 前端骨架；本地 JWT 鉴权（ADR-0010） | `schemas/event.py`, `web/src/api/`, `web/src/App.tsx` | 前端能拿到生成的类型 |
| D3 | SSE 通道（假事件）+ 前端 reducer 消费 | `core/sse.py`, `api/chat.py`, `features/chat/*` | 页面能看到流式输出与步骤条 |
| D4 | 事件落库 + `Last-Event-ID` 续传 | `models/run.py`, `api/runs.py`, `core/store.py` | 断网重连不丢消息、顺序正确 |
| D5 | 最小 Agent：单节点 + 假工具 `query_cmdb` + 工具卡片 | `agent/state.py`, `agent/graph.py`, `tools/registry.py` | Agent 能调一个工具并展示参数/结果 |

**风险**：D3 是本周关键路径。如果 SSE 当天没通，D4/D5 顺延，周末补。

---

## W2 RAG

| 天 | 任务 | 验收 |
|---|---|---|
| D6 | 造数据：50 篇 KB + 200 资产 + 500 工单（含噪声与冲突） | `server/app/seed/generate.py` 一条命令生成 |
| D7 | 解析（PyMuPDF/python-docx）+ 结构切分 + 元数据 | 上传 PDF 能看到 chunks 与 heading_path |
| D8 | embedding + pgvector HNSW + tsvector 索引 | 两种检索各自能返回结果 |
| D9 | 混合检索 + RRF + bge-reranker + 引用溯源 | 答案带 `[1][2]` 角标 |
| D10 | 评测 v0：20 条问答，出基线报告 | `app/eval/runner.py` 能出 markdown 报告 |

**关键指标**：recall@5 ≥ 0.7 才继续；低于 0.6 先修切分与检索，不要急着做 Agent。

**实现状态（2026-11-09）**

| 天 | 状态 | 落地 |
|---|---|---|
| D6 造数据 | ✅ | `seed/generate.py` 一条命令生成 50 文档 / 200 资产 / 500 工单（含过期版本、冲突、噪声），`--db` 同时写入 Postgres |
| D7 解析 + 切分 | ✅ | `rag/parse.py`（pypdf / python-docx / MD）、`rag/chunk.py`（标题路径 + 表格独立 chunk）、`POST /admin/kb/documents` 返回 chunks 与 heading_path |
| D8 embedding + 索引 | ✅ | `rag/embed.py`（哈希 / HTTP 两种）、pgvector HNSW + `tsvector` GIN，迁移 0003 |
| D9 混合检索 + 引用 | ✅ | tsvector + 向量 + RRF + 确定性重排 + 阈值 + 引用三元组；聊天回答带 `[1][2]` |
| D10 评测 v0 | ✅ | `eval/runner.py` 20 条出 markdown 报告；基线 [eval/baseline-v0.md](eval/baseline-v0.md) |

W2 指标：`recall@5 100%` / `cite_acc 91.7%` / `refusal_correct 100%` /
`injection_blocked 100%` / `p95 71ms`（20 条小样本，内存检索，口径见基线文档）。
W3 拆出 `classify` / `verify` 后同一命令为 `avg_steps 7` / `p95 83ms`，基线文档已同步。
与计划的差异：PDF 默认用 `pypdf` 而不是 PyMuPDF（体积与依赖原因，ADR-0011）；
重排是确定性规则，bge-reranker 留到 W4 有模型服务后再评估。

---

## W3 工具治理 + 审批（项目的灵魂）

| 天 | 任务 | 验收 |
|---|---|---|
| D11 | 意图识别：规则 + 小模型兜底 | 分类准确率 ≥ 85%（50 条标注） |
| D12 | 工具注册表 + 白名单 + 角色权限矩阵 | 管理页能看到矩阵 |
| D13 | 五道闸门 + 超时 + 错误分类重试 + 降级 | 20 条越权用例 100% 拦截 |
| D14 | `create_ticket` + 审批节点 + 审批卡 | 点批准后工单落库，点拒绝后不落 |
| D15 | 三条剧本端到端 + 修 bug | ①打印机离线 ②申请权限 ③知识问答 |

**三条剧本（必须能连续演示，不能靠重启）**

1. 打印机离线：查资产 → 检索 → 只读诊断 → 给出步骤 → 完成（无写操作）
2. 申请软件权限：检索政策 → 判断需审批 → 生成工单草稿 → **人工审批** → 落库
3. 知识问答：纯 RAG，带引用，无工具

**实现状态（2026-11-09）**

| 天 | 状态 | 落地 |
|---|---|---|
| D11 意图识别 | ◐（规则 + 模型兜底，未做标注集） | `agent/nodes/classify.py`：规则优先，模糊输入走小模型；`ticket_create` / `asset_check` / `knowledge` + 工单分类；**50 条标注准确率仍未测** |
| D12 注册表/角色矩阵 | ✅（代码） | `tools/registry.py` 已有 `ToolSpec.roles` / `enabled`；管理页矩阵留 W5 D23 |
| D13 五道闸门 + 重试 | ✅ | 五道闸门、入参白名单/enum、按工具超时、分类重试、`verify` 重规划一次、降级话术；`tests/test_tools_guard.py` 20 条 |
| D14 create_ticket + 审批 | ✅ | `approvals` 表 + `/api/approvals` + 审批卡；通过后从快照恢复 `act`，工单真正落 `tickets` |
| D15 三条剧本 | ✅ | `tests/test_playbooks.py` 连续跑三条剧本；审批/越权/幂等/超时见 `tests/test_approvals.py` |

W3 指标（本地）：后端 129 passed + 8 skipped；带 Postgres 137 passed；
`ruff`/`mypy`/`alembic check` 全绿；越权/自批/非审批人/重复决议/超时全部有测试。
与计划的差异：LangGraph 未启用，改用显式转移表（ADR-0012），理由与迁移路径见
[docs/04 §7](04-agent-design.md)；审批 `scope=session` 已落库（按 user + session + tool
隔离，默认 8 小时）；D11 的分类准确率验收项仍未完成（W4 只接了模型兜底，标注集留待补测）。

---

## W4 网关 + 观测

| 天 | 任务 | 验收 |
|---|---|---|
| D16 | 模型网关：provider 适配（OpenAI 兼容 / Ollama）+ 规则路由 | 简单意图走小模型（日志可见） |
| D17 | 滑动窗口限流 + 每日预算 + 失败切换 | 超预算直接拒绝，不抛 500 |
| D18 | token 成本埋点 + 聚合查询 | 每次 run 有 cost_cents |
| D19 | 成本看板 + 运行详情页 | 看板与 `model_calls` 对得上 |
| D20 | 回放：按 run_id 重放事件 + 失败归因打标 | 任意历史 run 可完整回放 |

**一致性测试**：`runs.token_in == sum(model_calls.token_in)`，写进 CI。

**实现状态（2026-11-09）**

| 天 | 状态 | 落地 |
|---|---|---|
| D16 模型网关 | ✅ | `gateway/`：OpenAI 兼容 + Ollama 原生适配、classify→local / plan→cloud 规则路由、失败切换；classify 兜底与 plan 均已接入 |
| D17 限流 + 预算 | ✅ | `core/limits.py`：Redis ZSET 滑动窗口 + UTC 日预算预扣/结算；超限 429，超预算 `run.failed(BUDGET_EXCEEDED)` |
| D18 token 计量 | ✅ | `model_calls` 表（迁移 0006）；计量行与 `runs` 汇总同事务增量更新；`tests/test_metrics_pg.py` 覆盖失败 run |
| D19 成本看板 | ✅ | `GET /runs`、`GET /admin/cost/summary`；前端 `/runs`、`/console/cost` |
| D20 回放 + 归因 | ✅ | `/runs/:id` 用事件 reducer 重建；`run.failed.category` + `runs.failure_category` |

W4 指标（本地）：后端 **192 passed**（含 Postgres，2 warnings）；默认无库 **180 passed + 12 skipped**；
前端 **28 tests** 且 `tsc`/`oxlint 0`/`oxfmt --check`/`pnpm build` 全绿；`alembic check` 无漂移。
评测仍是 mock/规则模式：20/20、recall@5 100%、cite_acc 91.67%、p95 87ms、avg_cost 0
（真实模型效果与成本需要配置 provider 后另跑，见 docs/08 §6）。
与计划的差异：D11 的 50 条标注分类准确率仍未测；`query_cmdb` 仍是内置假数据；
LangGraph 在 W4 评估后仍未启用（ADR-0012）。

---

## W5 前端打磨 + 管理后台

| 天 | 任务 | 验收 |
|---|---|---|
| D21 | 知识库管理（上传/列表/切片预览/重建索引） | 不写代码也能更新知识库 |
| D22 | 工具注册与试调用 | schema 编辑 + 试调用走治理链路 |
| D23 | 权限矩阵 + 审批中心 | 已办/待办可筛 |
| D24 | 对话体验：中断/重试/多轮/引用跳转/移动端 | 手机上能用 |
| D25 | 嵌入形态：iframe + postMessage + 主题变量 | 嵌到任意页面可用 |

**本周只做减法不做加法**：任何新想法写进 backlog，不加功能。

**实现状态（2026-11-09）**

| 天 | 状态 | 落地 |
|---|---|---|
| D21 知识库管理 | ✅ | `/console/kb`：上传（multipart）、列表筛选、切片预览 Dialog、重建索引；接口仍是 W2 的四个管理接口 |
| D22 工具注册/试调用 | ✅（schema 只读） | `tool_settings` 表（迁移 0007）+ `GET/PATCH /admin/tools` + `POST /admin/tools/{name}/test`；试调用强制走 `ToolGuard`，写工具只返回 `requires_approval` |
| D23 权限矩阵 + 审批中心 | ✅ | `GET/PUT /admin/perm-matrix`；`/console/perms` 勾选保存，`/console/approvals` 待办/已办筛选与决议（理由、`once/session`） |
| D24 对话体验 | ◐ | 失败重试（移除失败气泡、换新 `client_msg_id`）、移动端头部与输入区换行；引用仍只打开片段 Dialog，全文跳转等文档预览权限方案 |
| D25 嵌入形态 | ✗ 暂缓 | 需要 `postMessage` 来源白名单与 CSP `frame-ancestors` 的部署决策，不在没有安全边界时先做外嵌入口 |

W5 指标（本地）：后端 **215 passed**（含 Postgres，2 warnings）；默认无库
**201 passed + 14 skipped**；前端 **40 tests**，`tsc` / `oxlint 0` / `oxfmt --check` 全绿；
`pnpm build` 主包约 411KB、CostPage 490KB（无 >500KB 告警）；迁移到 **0007**，`alembic check` 无漂移。

与计划的差异：
- D22 的「schema 编辑」改成**只读**：schema 同时约束模型提示词与 `validate_args`，
  在线编辑会让两者脱节；工具定义继续走 code review，管理页只改启用/角色
- D25 未做，理由见上；W5 验收「非技术同事能传文档、配工具、看审批」已满足
- 角色目录是固定的 `employee/approver/admin` + 配置里的管理/审批角色，没有独立 roles 表
  （ADR-0014）；多副本下覆盖配置最长 2s 生效

---

## W6 交付

| 天 | 任务 | 验收 |
|---|---|---|
| D26 | 评测扩到 50 条 + 一键报告 | `make eval` 出完整报告 |
| D27 | 私有化 compose + 离线镜像 + 8C16G 压测 | 压测报告进 README |
| D28 | mock 模式 + demo 脚本 + 3 分钟录屏 | 无 key 可完整演示 |
| D29 | README + 架构图 + 部署文档 + 2 篇文章 | 陌生人 30 分钟能跑起来 |
| D30 | 简历条目定稿 + 面试问答演练 + 投递 | T2 岗位投出 |

---

## 每周固定动作

| 时点 | 动作 |
|---|---|
| 周一上午 | 看本周验收项，确认范围 |
| 每天结束 | 提交代码 + 更新 `docs/` 里对应章节的"实现状态" |
| 周三 | 自测一次端到端，早发现集成问题 |
| 周五 | 录 30 秒演示 GIF，发一条进度记录（为后面的文章积累素材） |

## 砍功能优先级（时间不够时从下往上砍）

1. 保留：三条剧本、工具治理、审批、引用溯源、成本计量、私有化部署
2. 可砍：移动端适配 → 知识库切片预览 → 工具 Schema 可视化编辑 → 运行列表分页
3. 可延后：Langfuse 集成、多副本部署、Tauri 桌面端、多 Agent 编排

## 里程碑检查点

| 检查点 | 判定 | 不达标怎么办 |
|---|---|---|
| W2 末 recall@5 < 0.6 | RAG 不成立 | 砍 rerank，先保引用与拒答；把召回问题写进复盘 |
| W3 末审批链路不通 | 核心价值缺失 | 砍掉只读诊断工具，保审批；必要时用轮询代替 SSE 续传 |
| W4 末成本对不上 | 计量不可信 | 先修埋点，宁可少统计也别统计错 |
| W5 末后台没做完 | 交付感不足 | 后台降级为"配置文件 + 只读页面" |
| W6 末跑不起来 | 交付失败 | 用 docker 全量打包，README 只保留一条命令 |
