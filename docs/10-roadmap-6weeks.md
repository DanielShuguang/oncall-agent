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
| 不清理 | `runs`（列表/成本/多轮上下文依赖）、审批记录、知识库；上传文件本来就不落盘，docs/02 的「附件 30 天」一行是 W2 设想，已删除 |
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

验证：默认 **315 passed + 24 skipped**；带 Postgres **339 passed**（2026-11-10 本机
WSL2 + Docker 复跑）；前端 **55 tests / 11 files**；`ruff` / `ruff format --check` /
`mypy`（95 files）/ `tsc --noEmit` / `oxlint` / `oxfmt --check` 全绿，`pnpm build` 成功；
迁移 0011 已 `downgrade → upgrade` 往返，`alembic check` 无漂移；开发库回填 307/310 场 run。

重跑 RAG 评测：**50/50**、`cite_acc 97.09%`、`recall@5 100%`、`p95 81ms`，与基线一致
（回收只影响读回放，不碰检索与提示词）。

已知边界：**fail-closed**——重新上传会换 `document_id`，旧引用因此按不可见处理，正常维护
知识库可能隐藏一批旧回答；回收只覆盖知识库引用（CMDB/工单/用户输入不在范围），
`runs.input/output` 的按时间保留（TTL）仍未做；读详情/回放多一次 `kb_documents` 查询，
没有延迟基准。详见 [ADR-0022](decisions/0022-run-content-visibility.md)。

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
