# 文档索引

> 先读 01，再按角色挑：后端看 02/03/04/05/06，前端看 07，交付看 08/09。

## 阅读顺序

| # | 文档 | 你会得到 | 什么时候读 |
|---|---|---|---|
| 1 | [01-architecture](01-architecture.md) | 系统全貌、模块边界、三条核心时序 | **第一天必读** |
| 2 | [02-data-model](02-data-model.md) | 表结构、事件模型、索引与一致性约束 | W1 D2 前 |
| 3 | [03-api-contract](03-api-contract.md) | REST + SSE 事件协议（前后端唯一契约） | W1 D2 前 |
| 4 | [04-agent-design](04-agent-design.md) | 8 节点状态机、规则优先、提示词策略 | W2 结束前 |
| 5 | [05-rag-design](05-rag-design.md) | 解析/切分/混合检索/rerank/引用 | W2 D6 前 |
| 6 | [06-tool-governance](06-tool-governance.md) | MCP、白名单、权限、超时、重试、审批 | W3 D11 前 |
| 7 | [07-frontend-design](07-frontend-design.md) | 路由、状态机、组件、流式与续传 | W1 D2 前 |
| 8 | [08-eval-metrics](08-eval-metrics.md) | 评测集设计、指标口径、报告格式 | W2 D10 前 |
| 9 | [09-deploy-private](09-deploy-private.md) | 私有化、离线镜像、信创适配 | W6 D27 前 |
| 10 | [10-roadmap-6weeks](10-roadmap-6weeks.md) | 30 天逐日任务与验收标准 | **每周一必看** |
| 11 | [11-dev-setup](11-dev-setup.md) | 环境搭建、常用命令、排错 | 第一天 |
| — | [eval/baseline-v1](eval/baseline-v1.md) | W6 评测基线（50 条、口径、复现命令） | 改检索/提示词前 |
| — | [eval/classify-v1](eval/classify-v1.md) | D11 意图分类基线（50 条标注，规则路径） | 改 classify 规则前 |
| — | [eval/multiturn-v2](eval/multiturn-v2.md) | 多轮评测基线（指代 + 话题切换 + 隔离对照，ADR-0024/0025） | 改 history / 检索参数前 |
| — | [eval/multiturn-v1](eval/multiturn-v1.md) | 多轮历史基线（ADR-0025 修复前，9 条） | 只看历史对比 |
| — | [eval/baseline-v0](eval/baseline-v0.md) | W2 历史基线（20 条） | 只看历史对比 |
| — | [decisions/](decisions/) | 49 篇 ADR：为什么 React / Python / LangGraph / pgvector / SSE / Tailwind+oxc / 依赖版本 / shadcn / Postgres 存储 / 本地 JWT / 离线 RAG 向量化 / 显式调度 / 自研模型网关 / 工具覆盖存库 / 私有化交付 / 审批事务 / 孤儿 run 回收 / 引用全文预览 / 文档级可见性 / 多轮上下文 / 数据保留 / 回答内容回收 / 正文按时间保留 / 多轮评测 / 追问原句优先 / 按用户日预算 / 审批快照保留 / 预算可观测性 / 工单自助查询 / 会话列表 / 历史引用回放 / PDF 解析子进程隔离 / 会话历史分页 / 资产查询接表 / 历史运行过程回放 / 批量会话详情 / 工具配置变更历史 / 工单详情查询 / 会话搜索 / 会话重命名 / 会话从列表移除 / 历史引用回填 / 已移除会话恢复 / 运行过程载荷上限 / 运行过程筛选与耗时聚合 / 审批等待时长 / 已移除会话分页与搜索 / 审批积压与等待统计 / 已移除会话批量恢复 | 面试前重读 |

## ADR（Architecture Decision Record）

| 编号 | 决策 | 一句话结论 |
|---|---|---|
| [0001](decisions/0001-react-over-vue.md) | 前端框架 | React 19，因为差异化在运行时不在框架，选生态更厚的一侧 |
| [0002](decisions/0002-python-fastapi.md) | 后端语言 | Python，因为目标岗位的显性要求，用 5 天学习换一个岗位池 |
| [0003](decisions/0003-langgraph.md) | Agent 编排 | 先手写 1 天 loop，再换 LangGraph，为 checkpoint 与可视化 |
| [0004](decisions/0004-pgvector.md) | 向量存储 | pgvector，5 万 chunk 量级下私有化组件最少 |
| [0005](decisions/0005-sse.md) | 流式协议 | SSE，单向 + 内网代理友好 + `Last-Event-ID` 原生续传 |
| [0006](decisions/0006-tailwind-and-oxc.md) | 前端样式与代码约束 | Tailwind CSS 4 承载样式，oxc（oxlint + oxfmt）替代 Biome |
| [0007](decisions/0007-dependency-versions.md) | 依赖版本 | 前端依赖跟最新（Vite 8 / Vitest 5 / React Router 8），TypeScript 用 6.0、7.0 暂缓 |
| [0008](decisions/0008-shadcn-components.md) | 组件层 | shadcn/ui：源码复制 + radix-ui 行为，令牌映射到既有色板 |
| [0009](decisions/0009-run-store-postgres.md) | 运行态存储 | Postgres + 事件投影；`seq` 行锁生成，内存实现只用于测试 |
| [0010](decisions/0010-local-jwt.md) | 鉴权 | 本地签发 JWT（HS256），不接 SSO；身份只来自 token |
| [0011](decisions/0011-offline-rag-vectorizer.md) | 离线 RAG 向量化 | 默认哈希向量 + pypdf，不把 torch / PyMuPDF 2.x 装进默认依赖；可切 HTTP embedding |
| [0012](decisions/0012-explicit-agent-scheduler.md) | Agent 调度 | W3 用显式转移表（8 节点 + 审批恢复），LangGraph W4 评估后仍未启用 |
| [0013](decisions/0013-model-gateway.md) | 模型网关 | 自研薄层：规则路由 + provider failover + 计量/预算；不用 LiteLLM |
| [0014](decisions/0014-tool-policy-overrides.md) | 工具配置 | 定义留在代码，数据库只存启用/角色覆盖；schema 只读，代码禁用不可绕过 |
| [0015](decisions/0015-private-delivery.md) | 私有化交付 | 单 compose + `full` profile；镜像内迁移/按需 seed；Nginx 反代 SSE；离线 tar；压测只承诺口径 |
| [0016](decisions/0016-approval-decision-transaction.md) | 审批事务 | 决议状态 + `approval.resolved` + 拒绝/超时 `run.failed` 同一事务；恢复执行仍是独立窗口 |
| [0017](decisions/0017-stale-run-recovery.md) | 孤儿 run 回收 | 超过 stale 阈值的 `running` run 追加 `run.failed(RUN_INTERRUPTED)` 收敛；只改状态，不重放写操作 |
| [0018](decisions/0018-citation-fulltext-preview.md) | 引用全文预览 | 登录即可读引用文档全文（与检索同一可见性），不提供列表；将来做文档级 ACL 必须先在检索侧过滤 |
| [0019](decisions/0019-document-level-access.md) | 文档级可见性 | `public` / `roles` 两档，角色交集判定，`admin` 是知识库所有者；召回 SQL 在 `LIMIT` 之前过滤，预览用同一规则；不可见返回 404 |
| [0020](decisions/0020-multi-turn-context.md) | 多轮上下文 | 历史只从服务端同用户同会话的 `runs` 投影取 3 轮，客户端不传；只用于理解指代，不进证据链 |
| [0021](decisions/0021-data-retention.md) | 数据保留 | 过期事件按 run 整场清理（默认 180 天）并标记 `events_pruned_at`；计量只删明细、保留 `runs` 汇总；不删 runs / 审批 / 知识库 |
| [0022](decisions/0022-run-content-visibility.md) | 回答内容回收 | 回答引用快照落 `runs.cited_document_ids`；读详情/事件/重放/多轮历史时按**当前**可见性校验，引用文档不可见就隐藏正文（fail-closed，不改写历史） |
| [0023](decisions/0023-run-content-retention.md) | run 正文按时间保留 | `runs.input/output` 到期清空并写 `content_pruned_at`，只留摘要；强制正文保留期 ≥ 事件保留期（事件里是同一段正文）；与按权限回收正交 |
| [0024](decisions/0024-multiturn-eval.md) | 多轮评测 | 追问轮按「引用命中 + 空会话隔离对照」判定指代解对（`coref_acc`）；独立基线不与单轮主集混算；评测顺带修好连续追问丢话题锚点的 `context_query` |
| [0025](decisions/0025-followup-original-first.md) | 追问的原句优先 | 追问先按原句检索：话题头点名了第一名文档且领先 ≥ 0.10 就不拼上文；新话题单独记 `shift_acc`，守卫用例防过度触发 |
| [0026](decisions/0026-user-daily-budget.md) | 按用户日预算 | 默认值 + `user_budgets` 表覆盖；独立个人账本（UTC 日、Redis/内存）；网关在调用前拒绝，个人不足时把全局预扣还回去 |
| [0027](decisions/0027-approval-snapshot-retention.md) | 审批快照保留 | 已决议审批的 `state` 按正文保留期清空为 `{}`（无迁移、幂等），参数/理由/决议人永久保留；`approval_grants` 过期即删 |
| [0028](decisions/0028-budget-observability.md) | 预算可观测性 | 两本账暴露只读快照（预扣时间戳放同一 hash、用户用当日集合枚举）；`/admin/budgets/usage` 出账本口径，管理页与配置拼表；账本故障 503 不降级 |
| [0029](decisions/0029-ticket-self-service-query.md) | 工单自助查询 | `query_tickets` 只读、身份注入、只查本人；状态问法不新增意图，规则计划选中、`finalize` 以工单表作答（不拼知识库引用）；无迁移 |
| [0030](decisions/0030-session-list.md) | 会话列表 | 不建表，按 `runs.session_id` 投影（无迁移）；`GET /sessions` 只读本人、标题取最早非空 input；点开只读回放并沿用 session 继续，不落 localStorage |
| [0031](decisions/0031-run-citations-replay.md) | 历史引用回放 | `runs.citations` 存引用快照（迁移 0014），历史会话还原角标；正文回收/过期时一并置空，不回填旧 run |
| [0032](decisions/0032-pdf-parse-subprocess.md) | PDF 解析子进程隔离 | `.pdf` 走 `spawn` 子进程与 60 秒超时；崩溃/超时收敛为 422，不再带走 API；仍不做 OCR，未限内存 |
| [0033](decisions/0033-session-history-pagination.md) | 会话历史分页 | `/sessions` 用 `(updated_at, session_id)` keyset 游标，`/runs` 沿用已有游标翻更早轮次；翻页可能重复/跳过，无新表/迁移 |
| [0034](decisions/0034-cmdb-assets-table.md) | 资产查询接表 | `query_cmdb` 改读 `assets` 表（内存/PG 双实现），`owner_id` 从 schema 删除、由 `ToolGuard` 注入；空结果是合法结果；无迁移 |
| [0035](decisions/0035-run-timeline-replay.md) | 历史运行过程回放 | 历史详情从事件投影只读工具/审批（最多 20 项），跟随回答可见性；不返回审批人身份；事件仍是唯一真相，无迁移 |
| [0036](decisions/0036-session-detail-batch.md) | 批量会话详情 | 新增 `GET /sessions/{id}/runs`：一页 run 的正文/引用/过程一次返回；可见性与事件批量查；无 `model_calls`、无新表/迁移 |
| [0037](decisions/0037-tool-setting-history.md) | 工具配置变更历史 | 追加式 `tool_setting_changes`（迁移 0015）：每个真正变化的工具一行、与配置写入同事务；admin-only 按工具查历史；不清理、不回滚 |
| [0038](decisions/0038-ticket-detail.md) | 工单详情查询 | `query_tickets` 增加可选 `ticket_id`：按 `requester` 过滤的单条查询，查不到返回 null、不泄露存在性；`finalize` 用描述/处理人/解决时间直答；无迁移 |
| [0039](decisions/0039-session-search.md) | 会话列表按标题搜索 | `GET /sessions?q=` 只搜投影标题（最早非空 input）、本人、大小写不敏感子串；Postgres 用窗口函数 + `strpos`，与 keyset 分页共用游标；无新表/索引/迁移 |
| [0040](decisions/0040-session-rename.md) | 会话重命名 | 旁挂 `session_titles`（迁移 0016、复合主键、无外键）：显示标题优先自定义；`PATCH /sessions/{id}` 1–60 字符、null 恢复默认；搜索同时匹配自定义标题与首条问题；不碰 run/事件/排序 |
| [0041](decisions/0041-session-remove.md) | 会话从列表移除 | 旁挂 `hidden_sessions`（迁移 0017、复合主键、无外键）：`DELETE /sessions/{id}` 软移除，204/404/503、幂等；只过滤列表与标题搜索，不删 run/事件/审批，直连详情仍可读；v1 无恢复 |
| [0042](decisions/0042-citation-backfill.md) | 历史引用回填 | 一次性 CLI `backfill-citations`（`--dry-run`/`--limit`）：只处理无快照、正文与事件都未清理的 run，从最后一条 `message.completed` 重建并条件写入；不改读路径/保留语义，无迁移 |
| [0043](decisions/0043-hidden-session-restore.md) | 已移除会话恢复 | `GET /sessions/hidden` 列本人移除项、`DELETE /sessions/{id}/hidden` 只删 `hidden_sessions` 行；恢复后重新参与列表与搜索，不碰 run/事件/审批；无迁移 |
| [0044](decisions/0044-timeline-payload-cap.md) | 运行过程载荷上限 | 读取侧把单个工具参数/结果压到 4096 字符（前 1024 字符预览），条目带 `truncated`；事件与 DB 原始载荷不动；无迁移 |
| [0045](decisions/0045-timeline-filter-summary.md) | 运行过程筛选与耗时聚合 | 纯前端：类型/工具名筛选、异常计数、工具耗时之和与最慢调用；只对已返回的 20 项计算，不改接口、无迁移；「异常」是展示口径，不是新状态机 |
| [0046](decisions/0046-approval-wait.md) | 审批等待时长回放 | 审批项加 `requested_at` 与 `waited_ms`（事件差值，仅已决议项）；负数/孤儿省略；不进入工具耗时汇总，身份仍隐藏；无迁移 |
| [0047](decisions/0047-hidden-session-pagination.md) | 已移除会话分页与搜索 | `GET /sessions/hidden` 增加 `(hidden_at, session_id)` keyset 游标与标题搜索；与主列表同口径、搜索不搜正文；无迁移/新索引 |
| [0048](decisions/0048-approval-stats.md) | 审批积压与等待统计 | `GET /approvals/stats?days=7`（仅审批人）：待办数/最久等待 + 窗口内已决议的平均/最长等待；先收敛超时，过期不计；无迁移 |
| [0049](decisions/0049-hidden-session-batch-restore.md) | 已移除会话批量恢复 | `POST /sessions/hidden/restore`：一次 1–50 个、去重、部分成功；只删本人 `hidden_sessions` 行，返回 `{restored, requested}`；无迁移、无审计 |

> ADR 的写法：背景 → 方案对比 → 决策 → 后果。面试被问"为什么这么做"时，直接念 ADR。

## 约定

- 让 AI 编码助手参与开发前，先读仓库根目录的 [AGENTS.md](../AGENTS.md)：那里是可执行的约束（硬规则 R1–R13、常见任务 recipe、反模式清单）
- 所有时间戳为 UTC（`timestamptz`），前端本地化显示
- 金额单位为「分」（整数），避免浮点误差
- 事件序号 `seq` 在单个 run 内严格递增，从 1 开始
- 文档与代码不一致时，**以文档为准并提 PR 改代码**（文档是契约）
