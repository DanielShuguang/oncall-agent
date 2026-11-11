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
| D11 意图识别 | ✅（50 条标注 50/50，样本内） | `agent/nodes/classify.py`：规则优先，模糊输入走小模型；`ticket_create` / `asset_check` / `knowledge` + 工单分类；`app/eval/classify.py` + `classify_cases.yaml` 出混淆矩阵，见 [docs/08 §3.1](08-eval-metrics.md) |
| D12 注册表/角色矩阵 | ✅（代码） | `tools/registry.py` 已有 `ToolSpec.roles` / `enabled`；管理页矩阵留 W5 D23 |
| D13 五道闸门 + 重试 | ✅ | 五道闸门、入参白名单/enum、按工具超时、分类重试、`verify` 重规划一次、降级话术；`tests/test_tools_guard.py` 20 条 |
| D14 create_ticket + 审批 | ✅ | `approvals` 表 + `/api/approvals` + 审批卡；通过后从快照恢复 `act`，工单真正落 `tickets` |
| D15 三条剧本 | ✅ | `tests/test_playbooks.py` 连续跑三条剧本；审批/越权/幂等/超时见 `tests/test_approvals.py` |

W3 指标（本地）：后端 129 passed + 8 skipped；带 Postgres 137 passed；
`ruff`/`mypy`/`alembic check` 全绿；越权/自批/非审批人/重复决议/超时全部有测试。
与计划的差异：LangGraph 未启用，改用显式转移表（ADR-0012），理由与迁移路径见
[docs/04 §7](04-agent-design.md)；审批 `scope=session` 已落库（按 user + session + tool
隔离，默认 8 小时）；D11 的分类准确率在 W3 时未测，W6 后补了 50 条标注集
（规则路径 50/50，样本内；模型兜底路径仍需真实 provider 才可量化）。

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
与计划的差异：D11 的 50 条标注分类准确率在 W4 时仍未测（W6 后已补，见上）；
`query_cmdb` 仍是内置假数据；
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
| D24 对话体验 | ✅ | 失败重试（移除失败气泡、换新 `client_msg_id`）、移动端头部与输入区换行；引用全文跳转与多轮上下文都在 W6 后补完（见下节），加载失败退回片段 |
| D25 嵌入形态 | ✗ 暂缓 | 需要 `postMessage` 来源白名单与 CSP `frame-ancestors` 的部署决策，不在没有安全边界时先做外嵌入口 |

W5 指标（当时，本地）：后端 **215 passed**（含 Postgres，2 warnings）；默认无库
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

**实现状态（2026-11-09）**

| 天 | 状态 | 落地 |
|---|---|---|
| D26 评测 50 条 | ✅ | `app/eval/cases/` 拆成 fact 15 / troubleshoot 15 / multihop 10 / negative 5 / injection 5；报告加 `tool_success_rate` 与分类失败归因；3 轮均值见 [eval/baseline-v1](eval/baseline-v1.md) |
| D27 compose + 离线镜像 | ✅（8C16G 未验收） | `server/Dockerfile`（uv 固定版本 + entrypoint 迁移/按需 seed）、`web/Dockerfile`（Node 构建 + Nginx SSE 反代）、compose `full` profile、`docker-compose.offline.yml`、`make images`、`app/eval/loadtest.py`。本机 registry 拉 Node 基础镜像超时，web 的 Node 构建层未在本机跑完；用 `pnpm build` + Nginx 镜像验证了运行态（SPA 200、SSE 透传、审批链路） |
| D28 mock + demo | ✅（录屏未做） | mock 模式本就无 key；`app/eval/demo.py` 打三条剧本（第三条真实走审批）；`make demo`；3 分钟录屏属于人工交付物，未提交 |
| D29 README + 部署文档 | ◐ | README 快速开始/评测/压测/局限已更新；`docs/09` 已补容器与离线命令；架构图沿用 README 文本图；两篇外部文章未写 |
| D30 简历/投递 | ✗ | 不属于代码交付，未做 |

W6 指标：评测 **50/50**（`cite_acc 97.09%`、`p95 81ms`、3 轮）；
后端默认 **205 passed + 14 skipped**、带 Postgres **219 passed**；前端 40 tests；
压测 **100/100** 成功、12.60 run/s、306.6 事件/s（开发机 16 vCPU/15GiB，非 8C16G 验收）；
迁移仍 **0007**，`alembic check` 无漂移。

与计划的差异：
- 8C16G 压测目标未在 8C16G 机器上验收，只跑了开发机链路验证；不把开发机数字写成生产容量
- 影像资料（3 分钟录屏、30 秒 GIF）未产出，README 用文字与命令替代
- 离线镜像需在客户内网重跑 `docker compose -f docker-compose.offline.yml up -d` 做最终验收

---

## W6 后加固（2026-11-09）

W6 交付完成后补三个遗留项：D11 的意图分类验收、会直接影响审批可信度的事务边界，
以及进程中断后没人收敛的 `running` run；都不新增产品功能。

| 事项 | 落地 |
|---|---|
| 意图分类评测（D11 收口） | `app/eval/classify_cases.yaml` 50 条人工标注 + `app/eval/classify.py`（混淆矩阵、失败用例、模型兜底覆盖）；规则路径 **50/50**，`make eval-classify` 可复跑，基线见 [eval/classify-v1.md](eval/classify-v1.md)。结果属样本内，模型兜底路径未量化 |
| 审批决议原子性 | `ApprovalStore.resolve` 增加 `on_resolved` 回调；Postgres 在同一事务内写 `approvals.status` + `approval.resolved` + 拒绝/超时的 `run.failed`，事件失败则决议回滚；事件写入复用 `core/store.py: append_event_in_session`，seq/投影只有一份。[ADR-0016](decisions/0016-approval-decision-transaction.md) |
| 孤儿 run 回收 | 进程崩溃后停在 `running` 的 run，超过 `ONCALL_STALE_RUN_MIN`（默认 10 分钟）没有事件就追加 `run.failed(RUN_INTERRUPTED)`；`RunStore.fail_stale_run` 在事务内锁行复查，多副本同时回收只写一条。lifespan 后台任务 + `make reap`（`--dry-run` 先看候选），只收敛状态、不重放写工具。[ADR-0017](decisions/0017-stale-run-recovery.md) |
| 回归覆盖 | 新增 `tests/test_classify_eval.py`（50 条标注、验收线与报告口径）、`tests/test_approvals_pg.py` 两条事务回滚用例（首个事件失败、第二个事件失败）、`tests/test_recovery.py`（阈值/dry-run/审批等待不误杀/幂等/limit/最后活动时间优先）与 `tests/test_recovery_pg.py`（并发只写一条；契约测试内存与 Postgres 共用 `_exercise_stale`）；内存路径沿用原有审批/超时用例 |
| 文档 | docs/02 投影表、docs/06 §7 一致性边界、docs/09 §8 运维命令、README 已知局限同步；恢复执行仍在事务外，明确不自动重试写工具，回收只收敛状态 |

验证：默认 **222 passed + 17 skipped**；带 Postgres **239 passed**（2026-11-09 本机
WSL2 + Docker 复跑，含新增分类评测、审批事务回滚与孤儿回收并发用例）；
`ruff` / `ruff format --check` / `mypy` 通过。
改 classify 规则后重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`avg_tool_calls 0.36`，
未回退（单轮确定性运行，基线仍是 3 轮均值）。

---

## W6 后补：D24 引用跳全文（2026-11-09）

D24 只剩「引用只能看片段」。卡点是可见性：知识库预览接口一直是管理员的，
之前记的理由是「跨用户读原文需要单独授权」。这次把边界定清楚再实现。

| 事项 | 落地 |
|---|---|
| 可见性 | 预览与检索**共用同一可见性边界**：登录即可读引用文档全文；刻意不提供列表/浏览，只能凭已知的 `document_id` 打开（不校验引用关系，靠无列表 + UUID 收敛）；`/admin/kb/*` 仍要管理员。[ADR-0018](decisions/0018-citation-fulltext-preview.md) |
| 接口 | `GET /api/kb/documents/{id}/preview?chunk_id=&ord=`：返回文档字段 + 按 `ord` 重组的切片 + `focused_chunk_id` + `total_chunks` + `truncated`；展示路径只查正文列（不读向量/分词） |
| 窗口选择 | `app/rag/preview.py`：`chunk_id` 优先、`ord` 兜底、都对不上**不猜段落**；上限 200 切片 / 20 万字符；切片数或字符预算在引用段前用尽时前移/从引用段重新开窗，保证引用段一定在返回结果里 |
| 前端 | `CitationPreviewDialog`：按切片顺序渲染全文、引用段高亮并 `scrollIntoView`；加载失败退回引用片段并注明「不是全文」；底部写明实际显示范围、定位结果与「按切片重组」 |
| 边界 | 文档重新上传后 `document_id` 变化 → 旧引用 404；同文档重切后 `chunk_id` 变化 → `ord` 兜底；将来做文档级 ACL 必须先在检索侧过滤 |

验证：默认 **237 passed + 18 skipped**；带 Postgres **255 passed**（2026-11-09 本机
WSL2 + Docker 复跑）；前端 **44 tests**；`ruff` / `ruff format --check` / `mypy` /
`tsc --noEmit` / `oxlint` / `oxfmt --check` 全绿；迁移无变化（`alembic check` 无漂移）。

---

## W6 后补：文档级可见性（ADR-0019）

D24 把引用补成可跳全文之后，知识库对任何登录员工都可读，README 的已知局限里
一直挂着「暂不做文档级 ACL」。这次把它做掉，并且兑现 ADR-0018 留下的约束：
**ACL 必须先在检索侧过滤**。

| 事项 | 落地 |
|---|---|
| 数据 | `kb_documents.visibility`（`public`/`roles`）+ `allowed_roles varchar(32)[]` + CHECK 互斥；迁移 0008，存量文档落 `public`（升级不改变可见性） |
| 规则 | `app/rag/access.py`：`public` 所有人可读，`roles` 要求角色交集，`admin` 是知识库所有者（上传/删除本来就能改内容，隐藏正文只会让管理页切片预览自相矛盾） |
| 检索 | 两路召回的 SQL 在 `JOIN kb_documents` 后于 `LIMIT` 之前过滤；内存实现用同一规则。`tests/test_rag_pg.py` 用 (可见性 × 角色) 矩阵逐条比对 SQL 与 `is_visible()`，`tests/test_rag_acl.py` 覆盖内存实现与规则表 |
| 预览 | `GET /kb/documents/{id}/preview` 用同一条规则；不可见与不存在都返回 `404 NOT_FOUND`（403 会泄露文档存在） |
| 管理 | 上传带 `visibility`/`allowed_roles` 表单字段；新增 `PATCH /admin/kb/documents/{id}/access` 只改范围（不重切、`chunk_id` 不变，已有引用继续可点）；列表/详情回显可见范围 |
| 前端 | `/console/kb` 上传前选「公开 / 指定角色」，列表显示可见范围标签，行内「范围」按钮弹 Dialog 修改；角色解析与文案在 `features/console/access.ts`（纯函数，6 条 vitest） |
| 演示与评测 | seed 的 50 篇里把一篇噪声文档换成 `hr` 受限的薪酬文档（总数不变），`neg-bonus`（「年终奖什么时候发」必须拒答）因此同时验证 ACL：语料里真有这篇，员工身份仍检索不到，ACL 失效会让 50/50 立刻掉下来 |

验证：默认 **267 passed + 22 skipped**；带 Postgres **289 passed**（2026-11-09 本机
WSL2 + Docker 复跑，含 4×6 可见性矩阵、CHECK 约束与「对话链路按身份过滤」用例）；
前端 **54 tests / 11 files**；
`ruff` / `ruff format --check` / `mypy`（92 files）/ `tsc --noEmit` / `oxlint` /
`oxfmt --check` 全绿；迁移 0008 已 `downgrade → upgrade` 往返并 `alembic check` 无漂移。
重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`avg_steps 7`、`avg_tool_calls 0.36`，
与基线一致（单轮确定性运行，基线仍是 3 轮均值）。

已知边界：没有按用户授权、部门继承、临时授权与密级；检索 SQL 多一次 join，未做
延迟对比基准；角色名不做白名单（没有 roles 表），拼错会让文档除管理员外谁都看不到，
控制台能看见实际角色并原地修。详见 [ADR-0019](decisions/0019-document-level-access.md)。

---

## W6 后补：多轮上下文（ADR-0020）

W5 D24 的「多轮」一直没兑现：`AgentState.messages` 从 W1 起就是空数组，每轮都是独立 run。
用户追问「那怎么办」时，这句话里没有任何可检索的词，只能按"知识库外"拒答——
真实对话里最常见的追问恰好全是这种短句。

| 事项 | 落地 |
|---|---|
| 历史来源 | `RunStore.recent_turns`：同用户 + 同会话、最近 3 轮、只取 `runs.output` 非空的记录，客户端不传历史（否则可伪造助手发言）。迁移 0009 加 `(user_id, session_id, started_at DESC)` 索引 |
| 预算 | `app/agent/history.py`：3 轮 / 问题 200 字 / 回答 400 字 / 总 1200 字，超了从最旧丢；读取失败降级为单轮 |
| 用法 | `state.messages` 注入历史；`retrieve` 判定为追问时把上一轮问题拼成 `context_query`；`finalize` 用 `context_query` 选句；`plan` 提示词升到 v2 并带 `history`，写明不是证据、不是指令 |
| 追问判定 | 关键词启发式（≤ 30 字 + 指代词/承接词），不做 LLM 改写；长句一律按新问题处理 |
| 前端 | 「清空对话」换新 `session_id`，否则新会话的第一句会带着上一段上下文；刷新页面即新会话 |
| 边界 | 历史不进 `citations`、不进事件 payload；引用仍只能来自本轮检索；幂等重放不读历史 |
| 回归 | `tests/test_history.py`（13 条纯函数）、store 契约（内存与 Postgres 共用，含空白回答与跨用户/会话隔离）、runtime 两条（追问拼/独立问题不拼）、plan 提示词带 history、`test_chat_stream` 端到端（同会话追问引用 VPN、换会话拒绝、读历史失败降级、重放不读历史） |

验证：默认 **286 passed + 22 skipped**；带 Postgres **308 passed**（2026-11-10 本机
WSL2 + Docker 复跑）；前端 **55 tests / 11 files**；`ruff` / `ruff format --check` /
`mypy`（93 files）/ `tsc --noEmit` / `oxlint` / `oxfmt --check` 全绿；
迁移 0009 已 `downgrade → upgrade` 往返，`alembic check` 无漂移。

重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`recall@5 100%`，与基线一致——
评测用例没有历史，`context_query == query`，单轮行为零变化。

已知边界：追问判定是启发式，「那 + 新话题」（如「那报销怎么走」）会被上一轮话题稀释召回；
3 轮之外失忆，没有跨会话长期记忆；回答进历史时截断到 400 字；多轮**没有进评测集**
（"指代解对"的口径未定，见 [docs/08 §3.2](08-eval-metrics.md)）。详见
[ADR-0020](decisions/0020-multi-turn-context.md)。

---

## W6 后补：数据保留清理（ADR-0021）

docs/02 §4 从 W2 起就写着事件保留 30 天、计量 180 天，但**只有配置项、没有执行者**：
`ONCALL_EVENT_RETENTION_DAYS` 是死配置，`run_events` / `model_calls` 只增不删；
同时 docs/09 §9 要求「审计日志保留 180 天」，与 30 天的事件保留自相矛盾。这次把保留策略
变成可执行、可 dry-run、可解释的运维动作：过期事件按 run 整场清理，run 摘要继续保留。

| 事项 | 落地 |
|---|---|
| 事件清理 | 终态（completed / failed / interrupted）且 `finished_at` 早于 180 天（`ONCALL_EVENT_RETENTION_DAYS`）的 run，按 **run 整场**删除事件，同事务写 `runs.events_pruned_at`；`FOR UPDATE SKIP LOCKED` 分批，多副本不重复；轮内最多 `ONCALL_RETENTION_MAX_BATCHES`（默认 10）批，取不满一批即停；挂起审批/运行中的 run 永不清理。迁移 0010 加列与部分索引 `idx_runs_retention` |
| 计量清理 | `model_calls` 按 `created_at` 删过期明细（`ONCALL_MODEL_CALL_RETENTION_DAYS`，默认 180 天），`runs` 上的 token/cost 汇总保留；保留期内两表对账口径不变 |
| 不清理 | `runs`（列表/成本/多轮上下文依赖）、审批决议行、知识库；上传文件本来就不落盘，docs/02 的「附件 30 天」一行是 W2 设想，已删除。审批快照与过期授权后来由 [ADR-0027](decisions/0027-approval-snapshot-retention.md) 清理 |
| API 语义 | `GET /runs/{id}` 与列表 summary 增加 `events_pruned_at`；`/runs/{id}/events` 对已清理 run 返回 200 + 空数组（run 没消失），由详情字段解释；`event_count` 表示当前仍保留的条数 |
| 前端 | `/runs/:id` 在 `events_pruned_at` 有值时显示「事件已过保留期被清理」，时间线/工具调用标为不可用，摘要、计量、失败归因与 `run.output` 最终回答照常展示 |
| 触发 | 后台每 6 小时（`ONCALL_RETENTION_INTERVAL_S`）扫一轮，单轮最多 10 批 × 200 行，跑满记 `retention_backlog_remaining` warning；`make prune` / `python -m app.cli prune --dry-run` 立即处理或先看候选（dry-run 只预览第一批，`--limit` 覆盖单批上限） |
| 回归 | `tests/test_retention.py`（策略 12 条）、store 契约新增 `_exercise_prune`（内存 + Postgres 共用）、`test_runs_api.py`（清理后详情/事件/列表）、`test_metrics_pg.py`（计量清理与汇总不变）、`test_config.py`（0 值启动期拒绝） |

验证：默认 **300 passed + 23 skipped**；带 Postgres **323 passed**（2026-11-10 本机
WSL2 + Docker 复跑）；前端 **55 tests / 11 files**；`ruff` / `ruff format --check` /
`mypy`（94 files）/ `tsc --noEmit` / `oxlint` / `oxfmt --check` 全绿，`pnpm build` 成功；
迁移 0010 已 `downgrade → upgrade` 往返，`alembic check` 无漂移；
`python -m app.cli prune --dry-run` 在开发库返回候选与截止时间。

重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`recall@5 100%`、`p95 81ms`，与基线一致
（保留策略不碰检索与提示词）。

已知边界：超过保留期的 run 只能看摘要，没有冷归档；清理任务没做性能基准（单批 200 场、
每轮 10 批、6 小时间隔是保守默认值，按 1–2 条计量/run 约 4000–8000 run/天）；
`model_calls` 删除后，超出窗口的区间成本明细不可再核对
（`runs` 汇总仍在）；角色撤销后的旧回答仍在 `runs.output`，run 级保留与内容回收未做。
详见 [ADR-0021](decisions/0021-data-retention.md)。

---

## W6 后补：回答内容回收（ADR-0022）

ADR-0019 的文档级可见性只管检索与预览，**已经产生的 run 不会重算**：`runs.output` 与
`message.completed.citations[].snippet` 里都是当时可见文档的正文；用户角色被撤销后，
旧回放、事件补拉、幂等重试与下一轮追问仍能读到这些内容。ADR-0021 的「待定」里记着这条，
这次补上。

卡点有两个，决定了不能只在事件里现取引用：事件默认 180 天后会被整场清理（ADR-0021），
清理过的 run 就再也没法重算；文档范围又随时可能被改窄或删除。所以引用快照必须落在
`runs` 上，判定必须是读时的。

| 事项 | 落地 |
|---|---|
| 引用快照 | `message.completed.citations[].document_id` 投影到 `runs.cited_document_ids`（JSONB，去重保序、上限 50），与 `output` 同一事务写；迁移 0011 从存量 `message.completed` 用 `jsonb_path_query` 回填 |
| 读时校验 | `app/runs/content.py`：引用文档**全部**当前可见才展示，任何一篇不可见（改窄或删除）就整场回收；`admin`（知识库所有者）不受限；没有引用时直接放行，不查知识库 |
| 覆盖路径 | 详情 `output=null` + `content_redacted=true`；事件接口 200 + 空数组；幂等重放 403 `CONTENT_REDACTED`；多轮历史剔除该轮（跨轮合并成一次批量查询） |
| 规则复用 | `KnowledgeStore.visible_document_ids`：Postgres 复用召回的 `_visibility_clause`，内存实现用 `is_visible`；同一张 (visibility × 角色) 矩阵在 `test_rag_acl.py` 与 `test_rag_pg.py` 两边断言 |
| 不改存储 | 回收是读时判定：可见范围改回去，旧回答自动恢复；不重扫、不改写事件、不做分布式任务 |
| 前端 | `/runs/:id` 用 `content_redacted` 显示「引用的文档已不可见」，隐藏回答与回放，摘要/计量/失败归因照常 |

验证：默认 **316 passed + 24 skipped**；带 Postgres **340 passed**（2026-11-10 本机
WSL2 + Docker 复跑）；前端 **56 tests / 11 files**；`ruff` / `ruff format --check` /
`mypy`（95 files）/ `tsc --noEmit` / `oxlint` / `oxfmt --check` 全绿，`pnpm build` 成功；
迁移 0011 已 `downgrade → upgrade` 往返，`alembic check` 无漂移；开发库回填 308/311 场 run。

重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`recall@5 100%`、`p95 81ms`，与基线一致
（回收只影响读回放，不碰检索与提示词）。

已知边界：**fail-closed**——重新上传会换 `document_id`，旧引用因此按不可见处理，正常维护
知识库可能隐藏一批旧回答；回收只覆盖知识库引用（CMDB/工单/用户输入不在范围），
回答流式中途断开的半截内容没有 `message.completed`、也就没有引用快照，不在回收范围；
按时间的正文保留在 ADR-0023 单独处理（两者正交：权限回收可恢复，时间清理不可逆）；
读详情/回放多一次 `kb_documents` 查询，没有延迟基准。详见
[ADR-0022](decisions/0022-run-content-visibility.md)。

---

## W6 后补：run 正文按时间保留（ADR-0023）

ADR-0021 补了事件与计量的执行者，但明确留下 `runs` 行：`input/output` 是产品数据，
「谁能看」由 ADR-0022 解决，「留多久」一直没答案。私有化现场问「用户的问题和回答留多久」，
只能回答「永久」。

卡点是正文在事件里也有一份（`message.delta` / `message.completed.text`）：只清 `runs`
不清事件，等于把正文留在事件表里继续被回放。所以清理必须**先事件、后正文**，
并且配置层强制正文保留期不短于事件保留期。

| 事项 | 落地 |
|---|---|
| 到期清空 | `runs.content_pruned_at`（迁移 0012）+ `RunStore.prune_contents`：终态且 `finished_at` 早于 `ONCALL_RUN_CONTENT_RETENTION_DAYS`（默认 180 天）的 run，`input` 置空串、`output` 置 NULL，同一事务写标记；`SELECT ... FOR UPDATE SKIP LOCKED` 分批 |
| 保留摘要 | 不删行、不动计量/失败归因/引用快照：运行列表、失败率、成本看板与 `model_calls` 对账照常 |
| 配置约束 | `ONCALL_RUN_CONTENT_RETENTION_DAYS < ONCALL_EVENT_RETENTION_DAYS` 启动期拒绝（事件里是同一段正文）；现场把事件保留期调到 180 天以上时要同步调大正文保留期，错误信息给出两种改法 |
| 读路径 | 详情 `input: ""`/`output: null` + `content_pruned_at`；幂等重放 `410 CONTENT_EXPIRED`；多轮历史按 `output` 非空自然剔除；`content_redacted` 短路为 false（过期优先于权限，也不再查知识库） |
| 索引 | `idx_runs_content_retention (finished_at) WHERE content_pruned_at IS NULL`：事件先清，清完的行掉出 `idx_runs_retention`，正文清理不能复用 |
| 执行顺序 | 事件 → 正文 → 计量；两个标记都幂等；CLI `prune` 输出新增 `content_before` / `content_runs` |
| 前端 | `/runs/:id` 用 `content_pruned_at` 显示「正文已过保留期，已清空且不可恢复」，与 ADR-0022 的「不可见、可恢复」分开表述 |

验证：默认 **330 passed + 24 skipped**；带 Postgres **354 passed**（2026-11-10 本机 WSL2 +
Docker 复跑）；前端 **56 tests / 11 files**；`ruff` / `ruff format --check` / `mypy`（95 files）/
`tsc --noEmit` / `oxlint` / `oxfmt --check` 全绿，`pnpm build` 成功；迁移 0012 已
`downgrade → upgrade` 往返，`alembic check` 无漂移；开发库 `prune --dry-run` 输出
`content_before` 与 `content_runs`；真实 Postgres 上跑通「造一场 run → 回填到 200 天前 →
`prune` → 详情 `input` 空 / `output` null / `content_pruned_at` 有值 → 同 `client_msg_id`
重放 410」。

重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`recall@5 100%`、`p95 83ms`，与基线一致
（正文清理只动保留策略，不碰检索与提示词）。

已知边界：正文清理**不可逆**（只能靠备份）；清理后该轮从多轮上下文消失；正文保留期不能
短于事件保留期，想更早删正文要连事件一起调；按用户/租户的差异化保留期与清理性能基线
仍未做。详见 [ADR-0023](decisions/0023-run-content-retention.md)。

---

## W6 后补：多轮评测（ADR-0024）

多轮上下文（ADR-0020）一直**有实现、没度量**：docs/08 §3.2 写着「多轮不在评测集里」，
ADR-0020 的「待定」也记着「需要先定义"指代解对"的口径」。改 `history.py`、检索参数或
提示词时，多轮没有回归信号。

难点是口径而不是用例数量：追问句（「那怎么办」）单独检索没有实词，命中文档既可能是
"用上了上下文"，也可能是"碰巧"（「那要等多久」单独就能命中《软件安装与权限申请流程》）。
所以判定要拆成**引用命中标注文档 + 空会话隔离对照**两步。

| 事项 | 落地 |
|---|---|
| 独立评测 | `app/eval/multiturn.py` + `multiturn_cases.yaml`，`make eval-multiturn`；9 条正例 + 1 条诊断项，只判最后一轮；setup 失败用例即失败；门槛 `coref_acc ≥ 85%`（诊断项不计入） |
| 隔离对照 | 同一句追问在空会话再跑一次，不得命中同一篇文档；否则判「隔离对照不成立」（假通过） |
| 用例约束 | 第 2 轮起必须被追问启发式识别（否则 loader 直接报错）；setup 轮次与正例必须标 `must_cite_docs`、拒答类只能进诊断项且只能判 `must_refuse`（防止把失败用例标成诊断绕开门槛）；同一轮不能既要求命中又要求拒答；只剩诊断项直接报错；追问句避开文档实词 |
| 发现的缺陷 | 三轮回合暴露 `context_query` 只拼紧邻上一句：第三句检索词里没有 VPN，召回为空。修复为按时间累积最近 3 轮用户问题（仍受 80 字预算），两轮/单轮行为不变 |
| 基线 | `docs/eval/multiturn-v1.md`：`coref_acc 100%（9/9）`、隔离对照 9/9、诊断 0/1（「那报销怎么走」被保修话题带偏，已知边界） |
| 回归 | `tests/test_multiturn_eval.py` 18 条 + `tests/test_history.py` 新增 3 条；主集 50 条不受影响 |

验证：默认 **351 passed + 24 skipped**；带 Postgres **375 passed**（2026-11-10 本机
WSL2 + Docker 复跑）；`ruff` / `ruff format --check`（153 files）/ `mypy`（96 files）通过；
迁移无变化。重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`recall@5 100%`、`p95 83ms`，
与基线一致（上下文链对单轮零影响）。

已知边界：样本内（9 条正例参与过启发式设计）；只覆盖被启发式判定为追问的句子；
文档级判定（不看段落）；mock 规则路径，真实模型收益未量化；「那 + 新话题」的稀释
仍未修（需要双检索/原句优先的单独决策）。详见
[ADR-0024](decisions/0024-multiturn-eval.md)。

---

## W6 后补：追问的原句优先（ADR-0025）

多轮评测（ADR-0024）留下一个诊断项失败：「公司笔记本整机保修几年」→「那报销怎么走」，
合并检索词后被上一轮的保修文档带偏，语料里其实有《差旅报销流程》。ADR-0024 的「待定」
记了三种修法（双检索 RRF / 原句优先 / 名词短语判定），共同顾虑是会影响主集召回与延迟。

难点是**判定**而不是拼接：长度分不开（「那报销怎么走」6 个字是新话题，「那要多久」
6 个字是追问），分数也分不开（单独检索时「那怎么申请」0.710 比「那报销怎么走」0.631
还高），而合并一定赢（旧话题的词更多，打印机文档 0.916 vs VPN 0.721）。

| 事项 | 落地 |
|---|---|
| 原句优先 | `retrieve` 对追问先按原句检索；`names_top_document` 成立就用原句结果（`context_query` 也记原句），否则再拼上文。原句检索异常按"点不出"处理，回落到合并查询 |
| 证据一 | 话题头（`history.topic_head`，疑问词之前那截）与第一名文档标题共享一个 ≥2 字词：「那报销」→《差旅报销流程》；「那怎么处理」的话题头只剩一个「那」，「处理」只是问法谓语 |
| 证据二 | 第一名比第二名（不同文档）高出 ≥ 0.10：有第二名的两条切换用例 0.21–0.32（另两条只有一篇文档），没点名新话题的追问只有 0.006–0.056（表见 `docs/eval/multiturn-v2.md`）；「那差旅怎么申请」0.018 是已知漏判 |
| 评测 | 新增 `shift_acc`（话题切换正确率）：命中新话题 + 不得引用上一轮话题；隔离对照方向相反（空会话必须命中所列文档，守住用例档位）。4 条切换 + 3 条守卫 + 1 条诊断，`shift_acc ≥ 85%` 与 `coref_acc` 并列 |
| 守卫 | 「那怎么申请」「那流程是什么」必须继续用上一轮上下文——只加切换用例的话，放宽判定就能全过，指标失去意义 |
| loader | shift 必须写 `must_not_cite_docs`、不能标 diagnostic；coref 不许写 `must_not_cite_docs`；没有 shift 用例直接报错（否则 `shift_acc` 是空指标） |

验证：默认 **366 passed + 24 skipped**；带 Postgres **390 passed**（2026-11-10 本机
WSL2 + Docker 复跑）；`ruff` / `ruff format --check`（153 files）/ `mypy`（96 files）通过；
迁移无变化；前端未改动。多轮评测：**`coref_acc 100%（12/12）`、隔离对照 12/12、
`shift_acc 100%（4/4）`、切换前提 4/4、诊断 0/1**。重跑 RAG 主集：**50/50**、
`cite_acc 97.09%`、`recall@5 100%`、`p95 77–79ms`（3 次单次运行；基线 81ms 是 3 轮均值，
同一量级），
单轮路径没有历史，指标不变。

已知边界：**没点名任何文档**的新话题（「那公司年会抽奖怎么规定」）仍会被上一轮稀释，
诊断项 0/1；**点名了但分差不够**的也会退化（「那差旅怎么申请」0.547 vs 0.530）。
要修得让模型改写查询（多一次调用，会改变 2 个 LLM 节点的基线），
列入待定。点不出具体文档的追问多一次检索（多一次向量化），真实嵌入服务下的延迟未做基准；
分差阈值 0.10 与语料相关，语料翻倍或换 reranker 后要重新标定。详见
[ADR-0025](decisions/0025-followup-original-first.md)。

---

## W6 后补：按用户日预算（ADR-0026）

ADR-0013 定了单 run 与当日全局两层预算，「待定」里留着「按租户/按用户日预算要不要做成表」。
缺口的后果很具体：全局额度花完后所有人一起停，一个大用户就能让全公司当天不能用；
反过来也没法只给某个人开额度。企业现场要的是"成本能落到人头、改额度不重启"。

难点在**账本语义**而不是表结构：预扣与结算必须落在同一个后端（ADR-0013 的老问题），
全局与个人是两笔预扣、不是一次原子操作，个人被拒时要把已经扣掉的全局额度还回去。

| 事项 | 落地 |
|---|---|
| 上限来源 | `ONCALL_USER_DAILY_BUDGET_CNY`（默认 0 = 不限）为默认值；`user_budgets`（迁移 0013）按用户覆盖；`0` 是显式不限，`DELETE` 才回默认值 |
| 读取 | `UserBudgetPolicy`：整表读进 2s 缓存（与 ADR-0014 同一种取舍）；库故障保留上一份快照、不让聊天 500；管理页要求读真实值 |
| 账本 | `UserBudgetLedger`（内存 / Redis）：key 带 `user_id` + UTC 日，复用全局账本的 Lua，上限每次传入（覆盖随时可改） |
| 闸门 | 网关顺序：单 run 检查 → 全局预扣 → 个人预扣 → 调 provider；个人不足时先把全局预扣按 0 结算再失败；provider 失败时两笔都按 0 结算 |
| 接口 | `GET/PUT/DELETE /admin/budgets[/{user_id}]`（admin）；PUT 回读一次返回库里的 `updated_at`；`daily_cents` 0–1,000,000 |
| 展示 | 成本页新增「个人日预算」卡片；花费仍以 `model_calls` 为真相源，账本只做闸门 |

验证：默认 **390 passed + 27 skipped**；带 Postgres + Redis **417 passed**（2026-11-11 本机
WSL2 + Docker 复跑）；`ruff` / `ruff format --check`（147 files）/ `mypy app`（102 files）通过；
迁移 0013 已 `upgrade → check → downgrade 0012 → upgrade` 往返，`alembic check` 无漂移；
前端 `tsc --noEmit` / `oxlint` / `oxfmt --check` 通过、**58 tests / 11 files**、
`pnpm build` 成功。检索与提示词未改：主集 **50/50**、`cite_acc 97.09%`、`recall@5 100%`、
`p95 78ms`；未动 `history.py` 与检索参数，多轮基线重跑一次确认未变（`coref 12/12`、
隔离对照 12/12、`shift 4/4`、诊断 0/1）。

已知边界：没有租户/部门维度（`Identity` 只有 `user_id` + `roles`，等接 IdP）；个人账本从
配置生效后的第一次调用开始累计，当天此前已花的钱不计入额度（`model_calls` 有全量数据）；
被拦下是 `run.failed(BUDGET_EXCEEDED)` 而不是 429（429 只用于请求限流）；mock 模式不经过
网关，个人预算不生效；全局与个人是两笔独立预扣，进程崩在中间会留下全局预留——与
ADR-0013 已知的"预扣泄漏"同类，日切自愈、偏保守。详见
[ADR-0026](decisions/0026-user-daily-budget.md)。预扣泄漏的观测与个人「已用/上限」的展示
在 [ADR-0028](decisions/0028-budget-observability.md) 里补齐。

---

## W6 后补：审批快照与过期授权（ADR-0027）

docs/02 §4 的保留表里，`approvals / approval_grants` 一直写着「不清理，保留期未定」，
ADR-0021 的「待定」也记着同一件事。缺口的后果不是「行多」，而是**同一段内容有两个寿命**：
ADR-0023 按 180 天清掉 `runs.input/output` 与事件，但 `approvals.state` 里还留着挂起瞬间的
用户问题、检索命中与工具结果，永久可读；`approval_grants` 过期后也一直留着。

难点是这两张表混了两类数据：决议（谁、何时、结论、理由、参数）是治理证据，应该长期保留；
`state` 是执行工作副本，只服务「审批通过后恢复执行」，寿命应该跟内容走。

| 事项 | 落地 |
|---|---|
| 快照 | `approvals.state` 清空为 `{}`：只清 `status != 'pending'` 且 `resolved_at` 早于 `ONCALL_RUN_CONTENT_RETENTION_DAYS` 的行；复用正文保留期，不新增环境变量；挂起的审批永不清理 |
| 决议 | `args` / `risk_level` / `status` / `requested_by` / `resolved_by` / `reason` / `scope` / `resolved_at` 全部保留；接口本来就不返回 `state`，无可见变化 |
| 无迁移 | `{}` 不是合法快照，清空即回收标记；幂等，不需要新列或索引（schema 仍到 0013） |
| 授权 | `approval_grants` 中 `expires_at < now` 的行删除；过期授权本来就不再生效，审计在 `approvals` 的 `scope='session'` 决议行里（`approval.resolved` 事件随 run 事件按 ADR-0021 到期删除） |
| 执行者 | `RetentionSweeper` 两个新步骤，顺序「事件 → 正文 → 审批快照 → 过期授权 → 计量」；收手条件包含新计数，只剩快照积压时单轮仍继续取批 |
| 可观测 | `prune` CLI JSON 增加 `approval_snapshots` / `approval_grants`（dry-run 给候选数）；后台日志同名字段 |

验证：默认 **395 passed + 28 skipped**；接真实 Postgres（`pgserver` 临时实例，PostgreSQL 16.2 +
pgvector）后 **422 passed + 1 skipped**（本机没有 Redis，账本往返用例按既有条件跳过）；
`ruff` / `ruff format --check`（162 files）/ `mypy app`（102 files）通过；空库
`alembic upgrade head` 一次到 0013（本轮无新迁移）；`prune --dry-run` 输出
`approval_snapshots` / `approval_grants`，真实清理后快照为空、参数与理由保留；前端未改动。
检索、提示词、多轮判定均未改，未重跑评测。

已知边界：超过保留期的审批仍可查参数与决议，但**不能再从快照恢复执行**（这只发生在决议前）；
决议行永久保留，没有冷归档；快照按 `resolved_at` 计时、正文按 `finished_at` 计时，
前者不晚于后者，差的是一次恢复执行的耗时；
审批表很小、没有在真实体量上量过清理性能；不按人删审批（数据主体请求等接 IdP 后再做）。
详见 [ADR-0027](decisions/0027-approval-snapshot-retention.md)。

---

## W6 后补：预算可观测性（ADR-0028）

ADR-0026 把个人日预算做成了闸门，但它的两个「待定」都没有出口：预扣泄漏（进程崩在
`reserve` 与 `settle` 之间）只有 `budget_reserve_leaked` warning 日志；成本页只有配置
（默认值与覆盖表），看不到某个人今天用了多少、还剩多少。后果是账本与成本看板对不上时
没人能解释，预扣卡住也只能翻日志。

难点是三个口径不能混：配置回答「应该花多少」，账本回答「闸门现在扣了多少（含未结算）」，
成本看板回答「已经落库的实际花费」。报表必须说明自己是哪一个。

| 事项 | 落地 |
|---|---|
| 快照 | 两本账加只读 `snapshot()`；`LedgerSnapshot(spent_cents, reservations)`，年龄在读取时计算 |
| 时间戳 | 预扣时间写进同一个 reservations hash 的 `<token>:ts`，结算时同时删；旧副本不写 ts → 年龄未知、不报 stale；不新增 key，滚动升级兼容 |
| 用户枚举 | 当日集合 `oncall:budget:users:{day}` 在 reserve 的 Lua 里 `SADD`，避免 SCAN 误匹配 `...:reservations:*` |
| 判据 | `RESERVATION_STALE_S=300`（模型超时 20s 的 15 倍）固定，不加环境变量；只提示，不自动回冲 |
| 接口 | `GET /admin/budgets/usage`（admin）：全局与按用户的已用、未结算笔数/金额、最老年龄；只读账本，故障 503 `LEDGER_UNAVAILABLE` 不降级 |
| 管理页 | 预算表合并配置与账本：用户 / 今日已用 / 日上限 / 剩余 / 来源 / 修改人；未知花费显示「—」而不是 0；全局摘要显示卡住的预扣 |

验证：默认 **402 passed + 30 skipped**；设 `ONCALL_TEST_REDIS_URL` 后 **405 passed +
27 skipped**，再加临时 Postgres 为 **432 passed**。`ruff check` / `ruff format --check`
（164 files）/ `mypy app`（103 files）通过；前端 `tsc --noEmit` / `oxlint` /
`oxfmt --check` 通过、**60 tests / 12 files**、`pnpm build` 成功。本轮没有 SQL/迁移变化
（schema 仍到 0013）；检索、提示词与多轮判定未改，未重跑评测。

已知边界：报表是当前 UTC 日的采样，没有历史趋势与自动对账；旧格式预扣（无 ts）年龄未知，
`oldest_age_s` 为 null、不计 stale，日切自愈；按租户聚合与 ADR-0026 同属待 IdP 的一类；
stale 阈值固定 300 秒。详见 [ADR-0028](decisions/0028-budget-observability.md)。

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
