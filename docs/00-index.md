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
| 6 | [06-tool-governance](06-tool-governance.md) | 工具治理（MCP 目标形态，尚未接入）、白名单、权限、超时、重试、审批 | W3 D11 前 |
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
| — | [decisions/](decisions/) | 131 篇 ADR：为什么 React / Python / LangGraph / pgvector / SSE / Tailwind+oxc / 依赖版本 / shadcn / Postgres 存储 / 本地 JWT / 离线 RAG 向量化 / 显式调度 / 自研模型网关 / 工具覆盖存库 / 私有化交付 / 审批事务 / 孤儿 run 回收 / 引用全文预览 / 文档级可见性 / 多轮上下文 / 数据保留 / 回答内容回收 / 正文按时间保留 / 多轮评测 / 追问原句优先 / 按用户日预算 / 审批快照保留 / 预算可观测性 / 工单自助查询 / 会话列表 / 历史引用回放 / PDF 解析子进程隔离 / 会话历史分页 / 资产查询接表 / 历史运行过程回放 / 批量会话详情 / 工具配置变更历史 / 工单详情查询 / 会话搜索 / 会话重命名 / 会话从列表移除 / 历史引用回填 / 已移除会话恢复 / 运行过程载荷上限 / 运行过程筛选与耗时聚合 / 审批等待时长 / 已移除会话分页与搜索 / 审批积压与等待统计 / 已移除会话批量恢复 / 审批统计按日趋势 / 审批统计按工具/审批人分组 / 审批列表分页 / 已办审批按决议时间排序 / 已办审批筛选 / 批量恢复逐条结果 / 审批列表导出 CSV / 审批列表首屏总数 / 审批统计按小时分布 / 会话恢复审计 / 会话恢复审计分页 / 恢复审计按 session 反查 / 恢复审计 CSV 导出 / 恢复审计管理页 / 恢复审计列表总数 / 恢复审计统计 / 恢复审计统计按过滤 / 恢复审计按日期范围 / 审批统计聚合导出 / 会话置顶 / 恢复审计统计导出、审计日期快捷预设 / 会话批量移除 / 会话置顶上限 / 置顶容量提示、记住审计日期预设 / 窄屏会话抽屉 / 抽屉焦点陷阱 / 记住审计过滤与统计窗口、刷新恢复上次会话、切换账号清理本地偏好 / 置顶审计、分页、保留清理、CSV 导出、管理页、日期过滤、按日统计与首屏总数、统计跟随过滤、统计 CSV 导出、置顶审计日期快捷预设、置顶审计按小时分布、置顶上限可配置、CSV 导出下载审计、导出审计保留清理、导出审计列表 CSV、导出 CSV 内容哈希、工具历史日期筛选、工具历史 CSV 导出、工具历史分页与总数、工具历史变更人/来源过滤、工具历史游标过期、工具历史游标过期后的重新加载、窄屏会话抽屉左滑关闭、工具历史游标 TTL 可配置、工具历史双向排序、导出审计日期快捷预设、恢复已移除会话时恢复置顶、恢复审计统计的恢复置顶汇总、恢复审计统计未恢复置顶提示、工具配置变更历史回滚、回滚前差异预览、回滚来源独立、审批统计自动刷新、审批统计自动刷新开关与失败提示、回滚预览读取执行瞬间当前配置、置顶/导出审计页记住日期预设、置顶/导出审计页记住非日期过滤、回滚预览附带代码默认配置、工具配置变更历史批量回滚、审批统计自动刷新开关持久化、审批统计自动刷新间隔可配置、审批统计自定义刷新间隔、恢复审计统计按日恢复置顶、置顶审计统计窗口记忆、审批统计窗口记忆、审批统计分组记忆、工具配置变更历史保留清理、工具历史保留清理时间索引、会话列表翻页去重 | 面试前重读 |

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
| [0049](decisions/0049-hidden-session-batch-restore.md) | 已移除会话批量恢复 | `POST /sessions/hidden/restore`：一次 1–50 个、去重、部分成功；只删本人 `hidden_sessions` 行，返回 `{restored, requested}`（逐条 `items` 见 ADR-0055）；无迁移；审计见 ADR-0059 |
| [0050](decisions/0050-approval-trend.md) | 审批统计按日趋势与时间窗口 | `/approvals/stats` 增加 UTC 日 `daily`（稀疏、只算已决议）；前端 7/30/90 天切换；无迁移 |
| [0051](decisions/0051-approval-stats-groups.md) | 审批统计按工具/审批人分组 | 可选 `group_by=tool\|approver`，只聚合窗口内已决议；前 20 组 + `groups_truncated`；内存/PG 聚合，无迁移 |
| [0052](decisions/0052-approval-list-pagination.md) | 审批列表游标分页 | `GET /approvals?cursor=`：`(expires_at, created_at, id)` keyset；取满给游标；非法游标 400；无迁移 |
| [0053](decisions/0053-resolved-approval-order.md) | 已办审批按决议时间排序 | 已办 `(resolved_at, id)` 倒序 + 迁移 0018 部分索引；游标形状随 status 变化；待办顺序不变 |
| [0054](decisions/0054-approval-list-filters.md) | 已办审批筛选与游标绑定 | `tool/resolved_by/resolved_from/resolved_to` 仅限已办；UTC 半开日期；游标加 `f` 指纹，换筛选 400；无迁移、无新索引 |
| [0055](decisions/0055-hidden-restore-results.md) | 批量恢复逐条结果 | 响应加 `items` 布尔结果；`unhide_sessions` 返回恢复 id 集合；不区分 missing/forbidden，不泄露存在性；无迁移 |
| [0056](decisions/0056-approval-export-csv.md) | 审批列表导出 CSV | `GET /approvals/export` 按当前状态/筛选导出；最多 5000 条，`X-Export-*` 头暴露截断；不导出 `args`，公式注入前置单引号；无迁移 |
| [0057](decisions/0057-approval-list-total.md) | 审批列表首屏总数 | `GET /approvals` 第一页返回 `total`（同 status/筛选/身份），后续页为 null；新增 `ApprovalStore.count`，首屏多一次 COUNT；无迁移、无新索引 |
| [0058](decisions/0058-approval-hourly-distribution.md) | 审批统计按小时分布 | stats 新增 `hourly`（UTC 0–23 稀疏分布，含单数与平均等待）；与 daily 同窗口/同口径；PG `date_part` + 内存归桶；无迁移、无新索引 |
| [0059](decisions/0059-session-restore-audit.md) | 已移除会话的恢复审计 | 新增 `session_restore_audits`（一次恢复一行，JSONB 实际恢复 id，CHECK 计数一致）；删除与审计同事务；`GET /admin/session-restores`；独立 365 天保留；迁移 `0019`；分页见 ADR-0060，按 session 反查见 ADR-0061 |
| [0060](decisions/0060-session-restore-audit-pagination.md) | 会话恢复审计列表分页 | `GET /admin/session-restores` 增加 `cursor`/`next_cursor`：`(restored_at, id)` 倒序 keyset，游标绑定 `user_id`，非法/换过滤 400；无迁移、无新索引；导出见 0062，总数见 0064；前端页面见 ADR-0063 |
| [0061](decisions/0061-session-restore-audit-session-filter.md) | 恢复审计按 session 反查 | `GET /admin/session-restores` 增加 `session_id`（1–64），PG `session_ids @>`；迁移 `0020` 加 `jsonb_path_ops` GIN；带过滤时游标增加 `s` 并绑定该过滤，无过滤仍是 `{t,i,u}`，旧游标只兼容无 session 过滤；导出见 0062，页面见 0063，总数见 0064 |
| [0062](decisions/0062-session-restore-audit-export.md) | 会话恢复审计 CSV 导出 | `GET /admin/session-restores/export`：`user_id`/`session_id` 过滤，不接收 cursor/limit；最多 5000 条，`X-Export-*` 告知截断；CSV 六列（`session_ids` 为 JSON 数组，不含正文）；BOM/CRLF/公式注入防护；抽出 `app/core/csv.py` 与审批导出共用；无迁移；页面见 0063 |
| [0063](decisions/0063-session-restore-audit-console.md) | 会话恢复审计管理页 | 管理后台新增 `/console/audits`：复用列表/导出接口，按用户/会话精确过滤、20 条/页「加载更多」、导出当前过滤结果；只读、无后端/迁移；非管理员请求 403；首屏总数见 ADR-0064 |
| [0064](decisions/0064-session-restore-audit-total.md) | 会话恢复审计列表总数 | `GET /admin/session-restores` 第一页附 `total`（同 `user_id`/`session_id` 过滤），后续页 `null`；`RunStore.count_session_restore_audits` 内存/PG 同口径；计数失败 503；无迁移/新索引；前端首屏「共 N 条」+ 已加载条数；无页码/跳页 |
| [0065](decisions/0065-session-restore-audit-stats.md) | 会话恢复审计统计 | `GET /admin/session-restores/stats?days=` 返回窗口内 `restores`（操作数）、`users`（去重）、`sessions`（`restored_count` 之和）与 UTC 稀疏 `daily`；`days` 1–365 默认 30；默认全局，按用户/会话过滤由 ADR-0066 补上；无迁移；前端 7/30/90 天统计卡 |
| [0066](decisions/0066-session-restore-audit-stats-filters.md) | 会话恢复审计统计按过滤 | `stats` 增加可选 `user_id`/`session_id`（1–64），汇总与 `daily` 同列表口径；无过滤保持全局；无迁移；前端统计卡跟随已应用过滤；日期范围见 ADR-0067 |
| [0067](decisions/0067-session-restore-audit-date-range.md) | 会话恢复审计按日期范围 | 列表/导出/统计共用 UTC 自然日闭区间 `restored_from`/`restored_to`；两端同时提供、最多 365 天，越界 422；`days` 与日期范围二选一；游标按需加 `d`；无迁移；前端日期输入与统计跟随过滤 |
| [0068](decisions/0068-approval-stats-export.md) | 审批统计聚合导出 CSV | `GET /approvals/stats/export` 输出长表（`meta`/`summary`/`daily`/`hour`/`group`）；与统计同窗口/分组、仅审批人；分组截断显式告知；复用 CSV helper；无迁移；前端「导出统计」跟随当前窗口 |
| [0069](decisions/0069-session-pin.md) | 会话置顶 | 新增 `pinned_sessions`（PK `user_id+session_id`，迁移 `0021`）；`GET /sessions` 排序 `(pinned, updated_at, session_id)` 倒序，游标 `{t,s,p}` 且旧游标缺 `p` 按 false；`POST/DELETE /sessions/{session_id}/pin` 204 幂等、404 不泄露；隐藏同事务清置顶；前端行内按钮，旧后端隐藏 |
| [0070](decisions/0070-session-restore-audit-stats-export.md) | 恢复审计统计导出 | 新增 `GET /admin/session-restores/stats/export`；与 `/stats` 同参数/同窗口，同步导出 `section,key,day,value` 长表（meta/summary/daily），复用 `csv_document`；响应头汇总计数；前端统计卡按钮跟随当前窗口/过滤 |
| [0071](decisions/0071-audit-date-presets.md) | 审计日期范围快捷预设 | 纯前端快捷键：近 7/30/90 天、本月、上月，按 UTC 自然日闭区间一键应用；`now` 可注入的纯函数 + 单测；不改后端/契约，无迁移 |
| [0072](decisions/0072-session-batch-hide.md) | 会话批量移除 | 新增 `POST /sessions/hide`（1–50、去重、部分成功、幂等）；`hide_sessions` 单事务写 `hidden_sessions` 并清置顶；返回逐条 `items`；无迁移/审计；前端「管理」模式只选当前页 |
| [0073](decisions/0073-session-pin-limit.md) | 会话置顶数量上限 | 每用户最多 50 个置顶；已置顶幂等，新增超限 `409 PIN_LIMIT_REACHED`；内存/PG 同口径计数；软上限、无迁移；既有超限数据不回溯 |
| [0074](decisions/0074-session-pin-capacity.md) | 置顶容量提示 | `GET /sessions` 返回 `pinned_count`/`pin_limit`；前端达到上限时禁用未置顶行；旧后端回退 409；无迁移 |
| [0075](decisions/0075-audit-preset-memory.md) | 记住审计日期预设 | 只把预设 ID 存 `localStorage`（`oncall.audit-date-preset.v1`）；打开审计页自动应用；改动手填日期或清除不保存，只改用户/会话过滤保留；无效值与存储不可用静默回退；无后端/迁移 |
| [0076](decisions/0076-session-drawer.md) | 窄屏会话抽屉 | `<640px` 标题栏菜单按钮打开复用的 `SessionList` 抽屉；遮罩/Escape/X/选择或新会话关闭；≥640px 恢复常驻侧栏；不复制列表状态、无持久化/滑动；焦点与滚动由 ADR-0077 补上；无后端/迁移 |
| [0077](decisions/0077-session-drawer-focus-trap.md) | 抽屉焦点陷阱 | 打开焦点进 X、关闭回菜单；Tab/Shift+Tab 在抽屉内循环；背景 `overflow:hidden`；窄屏 `role=dialog`+`aria-modal`；≥640px 自动关闭；纯函数 `nextFocusTarget` + 4 tests；无依赖/迁移 |
| [0078](decisions/0078-audit-filter-memory.md) | 记住审计过滤与统计窗口 | `localStorage` 键 `oncall.audit-filters.v1` 存 `userId`/`sessionId`/`statsDays`；长度与 7/30/90 校验；首屏恢复过滤/输入/窗口；点筛选/切窗口写入，「清除」或默认值删除；日期预设仍由 ADR-0075 独立记忆；无后端/迁移 |
| [0079](decisions/0079-last-session-restore.md) | 刷新恢复上次会话 | `localStorage` 键 `oncall.last-session.v1` 只存 session_id（trim、1–64）；会话变化写入，新会话/隐藏当前会话清除；首屏列表确认仍可见且用户未手选/未发送时恢复；竞态 ref 防覆盖；失败不清记忆；仅首屏 20 条、不跨设备、无后端/迁移 |
| [0080](decisions/0080-local-preferences-on-account-switch.md) | 切换账号清理本地偏好 | 解析 JWT `sub`（不验签）比较新旧账号；subject 变化时清空 `oncall.last-session.v1`、`oncall.audit-filters.v1`、`oncall.audit-date-preset.v1`；同 subject 续签保留；清空 token 不主动清；不按账号命名空间存储、无后端/迁移 |
| [0081](decisions/0081-session-pin-audit.md) | 置顶审计 | `session_pin_audits` 只记显式 pin/unpin（重复、隐藏清理不写），与置顶行同事务；管理端 `GET /admin/session-pins` 按用户/会话/动作过滤，分页见 0082、保留清理见 0083、CSV 导出见 0084、管理页见 0085、日期范围见 0086；无外键；迁移 `0022` |
| [0082](decisions/0082-session-pin-audit-pagination.md) | 置顶审计分页 | `(created_at, id)` 倒序 keyset 游标，base64url `{t,i,f?}`，`f` 为过滤条件指纹（不存原始 id）；取满才给 `next_cursor`；换过滤复用游标 400；无迁移/新索引 |
| [0083](decisions/0083-session-pin-audit-retention.md) | 置顶审计保留清理 | 独立 `ONCALL_SESSION_PIN_AUDIT_RETENTION_DAYS`（默认 365 天）；`RetentionSweeper` 按 `created_at` 分批删除，支持 dry-run；`RetentionResult`/CLI/日志增加计数；CSV 导出见 0084、管理页见 0085；无迁移（仍 0022） |
| [0084](decisions/0084-session-pin-audit-export.md) | 置顶审计 CSV 导出 | `GET /admin/session-pins/export`，同列表过滤，最多 5000 条；五列元数据、BOM/CRLF/公式防护；`X-Export-Count`/`X-Export-Truncated`；复用 `csv_document`；无迁移 |
| [0085](decisions/0085-session-pin-audit-console.md) | 置顶审计管理页 | ConsolePage「置顶审计」只读页：用户/会话/动作过滤、20 条/页 keyset、按已应用过滤导出 CSV；无后端/迁移；日期范围见 0086、按日统计见 0087、首屏总数见 0088；无编辑 |
| [0086](decisions/0086-session-pin-audit-date-range.md) | 置顶审计按日期范围 | 列表/导出增加 UTC 自然日闭区间 `created_from`/`created_to`；两端同时、最多 365 天、单端/倒置/超长 422；内部半开窗口；游标指纹含日期；无迁移（仍 0022） |
| [0087](decisions/0087-session-pin-audit-stats.md) | 置顶审计按日统计 | 新增 `GET /admin/session-pins/stats?days=`；全局窗口 `pins`/`unpins`/`users`/`sessions` 与 UTC 稀疏 `daily`；`days` 1–365 默认 30；跟随过滤见 0089；无迁移；前端 7/30/90 天统计卡 |
| [0088](decisions/0088-session-pin-audit-total.md) | 置顶审计首屏总数 | `GET /admin/session-pins` 第一页返回同过滤 `total`，后续页 null；`count_session_pin_audits` 与列表共用过滤；计数失败 503；无迁移；前端显示「共 N 条 · 已加载 M 条」 |
| [0089](decisions/0089-session-pin-audit-stats-filters.md) | 置顶审计统计跟随过滤 | `GET /admin/session-pins/stats` 复用列表的 `user_id`/`session_id`/`action`/`created_from`/`created_to`；`days` 可选并与日期范围二选一；过滤后汇总/日趋势同口径；无迁移；管理页统计卡跟随已应用过滤 |
| [0090](decisions/0090-session-pin-audit-stats-export.md) | 置顶审计统计 CSV 导出 | `GET /admin/session-pins/stats/export`，与 `/stats` 同参数/同窗口；同步长表 `section,key,day,value`，`meta`/`summary`/`daily`，不截断；`X-Export-*` 头；无迁移 |
| [0091](decisions/0091-pin-audit-date-presets.md) | 置顶审计日期快捷预设 | 复用 ADR-0071 的近 7/30/90 天、本月/上月，按 UTC 一键应用；上次预设记忆由 ADR-0118 补上；按区间反推高亮；筛选卡/导出状态拆文件，页面 ≤300 行；无后端/迁移 |
| [0092](decisions/0092-session-pin-audit-hourly.md) | 置顶审计按小时分布 | `/stats` 增加 UTC 小时（0–23）稀疏 `hourly`，与 `daily` 同窗口/过滤；内存/PG 同口径；CSV 增加 `hourly` 段；无迁移；统计卡展示有活动时段 |
| [0093](decisions/0093-session-pin-limit-config.md) | 置顶上限可配置 | `ONCALL_SESSION_PIN_LIMIT`（默认 50）经 `build_store` 注入内存/PG；`GET /sessions` 返回实际 `pin_limit`，409 用实际上限；启动期拒绝 `<1`；无迁移 |
| [0094](decisions/0094-export-download-audit.md) | CSV 导出下载审计 | 迁移 `0023` 新增 `export_audits`；6 个导出端点成功后记录 `user_id`/`resource`/`filters`/`row_count`/`truncated`；写失败 503（fail closed）；管理员 `GET /admin/export-audits` 按用户/资源/UTC 日期过滤、keyset 分页、首屏 total；保留 365 天（ADR-0095） |
| [0095](decisions/0095-export-audit-retention.md) | 导出审计保留清理 | `ONCALL_EXPORT_AUDIT_RETENTION_DAYS`（默认 365）独立于事件/正文/恢复/置顶审计；`RetentionSweeper` 按 `created_at` 分批删除，`RetentionResult`/`prune` CLI/日志增加计数；无迁移（仍 0023） |
| [0096](decisions/0096-export-audit-list-export.md) | 导出审计列表 CSV | 第 7 种资源 `export_audits`；`GET /admin/export-audits/export` 同列表过滤、最多 5000 行，导出自身也写审计；迁移 `0024` 扩展 CHECK |
| [0097](decisions/0097-export-content-hash.md) | 导出 CSV 内容哈希 | `export_audits.content_sha256` 记录返回 CSV 的 SHA-256（含 BOM/CRLF）；旧记录为空；列表/CSV/页面展示，不做签名；迁移 `0025` 只加列 |
| [0098](decisions/0098-tool-history-date-range.md) | 工具变更历史日期范围 | `history` 增加 `since`/`until`；`GET /admin/tools/{name}/history?changed_from=&changed_to=`（UTC 自然日，两端同时、最多 365 天）；无迁移，利用 `(tool_name, changed_at DESC)` 索引；历史 Dialog 应用/清除日期 |
| [0099](decisions/0099-tool-history-export.md) | 工具变更历史 CSV 导出 | `GET /admin/tools/{name}/history/export`（同日期窗口、最多 5000 行）；导出自身写 `resource=tool_setting_history` 下载审计，失败 503；资源扩为 8 种，迁移 `0026` |
| [0100](decisions/0100-tool-history-pagination.md) | 工具配置变更历史分页与总数 | 历史增加 keyset `(changed_at,id)`、首屏 `total`、`next_cursor`；游标绑定工具/日期指纹，跨筛选 400；无迁移 |
| [0101](decisions/0101-tool-history-filters.md) | 工具配置变更历史按变更人/来源过滤 | 历史列表/导出增加 `changed_by`/`source`；指纹绑定完整筛选；无迁移 |
| [0102](decisions/0102-tool-history-cursor-expiry.md) | 工具配置变更历史游标过期 | 游标增加 1 小时有效期 `e`，过期 400 `CURSOR_EXPIRED`；不签名/无迁移 |
| [0103](decisions/0103-tool-history-cursor-reload.md) | 工具历史游标过期后的重新加载 | `ApiError` 透传 `code`；仅 `CURSOR_EXPIRED` 显示「重新加载」，按已应用筛选取第一页；不自动重放、无后端/迁移 |
| [0104](decisions/0104-session-drawer-swipe-close.md) | 窄屏会话抽屉左滑关闭 | 松手时按总位移判定：左滑 ≥80px 且水平 ≥ 垂直 1.5 倍；仅 `mobileOpen` 单指，无跟手动画、无依赖/后端/迁移 |
| [0105](decisions/0105-tool-history-cursor-ttl-config.md) | 工具历史游标 TTL 可配置 | `ONCALL_TOOL_HISTORY_CURSOR_TTL_MINUTES`（默认 60，范围 1–1440）经 `Settings.tool_history_cursor_ttl_s` 注入签发；解码仍只比较绝对 `e`；无迁移 |
| [0106](decisions/0106-tool-history-order.md) | 工具配置变更历史双向排序 | `/history` 与 `/history/export` 增加 `order=latest|earliest`；latest 用 before 倒序、earliest 用 after 升序；游标指纹纳入 order；无迁移 |
| [0107](decisions/0107-export-audit-date-presets.md) | 导出审计日期快捷预设 | 导出审计页复用审计页五个 UTC 日期预设，点击即按当前草稿提交；高亮只由已应用过滤反推；上次预设记忆由 ADR-0118 补上 |
| [0108](decisions/0108-hidden-restore-pin.md) | 恢复已移除会话时恢复置顶 | `hidden_sessions.was_pinned` 记录移除时是否置顶（迁移 `0027`）；恢复在用户锁内先删隐藏行并 `RETURNING was_pinned`，再按请求顺序与当前 `pin_limit` 容量尽力恢复；容量不足仍恢复但不置顶；恢复触发的置顶不写显式审计；旧行默认不恢复 |
| [0109](decisions/0109-restore-repinned-count.md) | 恢复审计记录恢复置顶数 | `session_restore_audits.repinned_count`（迁移 `0028`）记录恢复时实际恢复的置顶数；CHECK `0..restored_count`；列表/CSV/审计页展示，旧行为 0 |
| [0110](decisions/0110-restore-audit-repinned-stats.md) | 恢复审计统计的恢复置顶汇总 | 统计接口/CSV 增加窗口内 `repinned` 总和（`0..sessions`）；前端统计卡增加「恢复置顶」；无迁移，旧行按 0 |
| [0111](decisions/0111-restore-audit-unrestored-hint.md) | 恢复审计统计卡标注未恢复置顶数 | 前端按 `max(0, sessions - repinned)` 派生未恢复置顶数，仅在 >0 时显示提示；只说数量、不判断原本未置顶或容量不足；无后端/迁移 |
| [0112](decisions/0112-tool-setting-rollback.md) | 工具配置变更历史回滚 | `POST /admin/tools/{name}/history/{change_id}/rollback` 读取该条 `before` 快照写回；`before=null` 删除覆盖，代码禁用工具不能回滚开启；有变化才追加新历史，不改旧记录；无迁移 |
| [0113](decisions/0113-rollback-preview.md) | 回滚前差异预览 | 历史行「回滚」先打开确认 Dialog，展示记录时 `before → after`、目标与「实际 before 可能不同」；取消不写、确认后执行；无后端/迁移 |
| [0114](decisions/0114-tool-rollback-source.md) | 回滚来源独立 | 回滚追加的记录用 `source="rollback"`，普通 PATCH 仍 `tool`、矩阵仍 `matrix`；历史/导出 `source` 枚举扩为 3 种；旧记录不回填；无迁移 |
| [0115](decisions/0115-approval-stats-auto-refresh.md) | 审批统计自动刷新 | 页面可见时每 30 秒刷新审批统计，重新可见立即补拉；显示更新时间和手动刷新；自动刷新失败保留上一份统计；无后端/迁移 |
| [0116](decisions/0116-approval-stats-auto-refresh-toggle.md) | 审批统计自动刷新开关与失败提示 | 可暂停 30 秒轮询，关闭时移除定时器/可见性监听；重开立即补拉；自动刷新失败保留旧统计并提示；无后端/迁移 |
| [0117](decisions/0117-rollback-current-preview.md) | 回滚预览读取执行瞬间当前配置 | 新增只读 `GET /admin/tools/{name}/history/{change_id}/preview`；返回 current/target/changed/rollbackable/reason；代码禁用时预览返回不可回滚原因；执行仍重新读取；无迁移 |
| [0118](decisions/0118-audit-preset-memory.md) | 置顶/导出审计页记住日期预设 | 两页各用独立 `localStorage` key；打开自动应用上次预设；只存预设 ID，手填非预设窗口/清除删除；三页互不覆盖，切换账号清理；无后端/迁移 |
| [0119](decisions/0119-audit-page-filter-memory.md) | 置顶/导出审计页记住非日期过滤 | 两页各用独立 key；置顶页存用户/会话/动作，导出页存用户/资源；不存日期；trim/长度/枚举校验；打开合并预设与过滤，清除/切账号清理；无后端/迁移 |
| [0120](decisions/0120-rollback-code-default.md) | 回滚预览附带工具代码默认配置 | 预览响应增加 `code_default`（enabled/roles），用于解释 `current=null`；不查库、不改变只读语义；无迁移 |
| [0121](decisions/0121-tool-history-batch-rollback.md) | 工具配置变更历史批量回滚 | 多选后回滚到最早选中记录的 `before`；只写一条 `source="rollback"` 历史；1–50 条、全有或全无；无迁移 |
| [0122](decisions/0122-approval-refresh-preference.md) | 审批统计自动刷新开关持久化 | 浏览器 localStorage 存 `on`/`off`；缺失/损坏按开启；切换账号清理；无后端/迁移 |
| [0123](decisions/0123-approval-refresh-interval.md) | 审批统计自动刷新间隔可配置 | 15/30/60 秒三档，默认 30；非法/损坏回退 30；只重启本地定时器；切换账号清理；无后端/迁移 |
| [0124](decisions/0124-approval-refresh-custom-interval.md) | 审批统计自定义刷新间隔 | 5–300 秒整数，默认 30；15/30/60 仍是快捷档；非法/越界回退 30；只重启定时器；切换账号清理；无后端/迁移 |
| [0125](decisions/0125-restore-audit-daily-repinned.md) | 恢复审计统计按日恢复置顶数 | `daily` 增加 `repinned`（按 UTC 日求和的 `repinned_count`）；统计 CSV 每个日期多一行 `daily,repinned`；前端统计卡展示最近 7 个活动日恢复/会话/置顶；无迁移 |
| [0126](decisions/0126-pin-audit-stats-window.md) | 置顶审计统计窗口按浏览器记住 | `oncall.pin-audit-stats-window.v1` 只存 7/30/90，默认 30 不写；刷新/重开保持，清除与切换账号回默认；纯前端、无迁移 |
| [0127](decisions/0127-approval-stats-window.md) | 审批统计窗口按浏览器记住 | `oncall.approval-stats-window.v1` 只存 7/30/90，默认 7 不写；刷新/重开保持，切换账号回默认；纯前端、无迁移 |
| [0128](decisions/0128-approval-stats-group.md) | 审批统计分组按浏览器记住 | oncall.approval-stats-group.v1 只存 none/tool/approver，默认 none 不写；刷新/重开保持，切换账号回默认；纯前端、无迁移 |
| [0129](decisions/0129-tool-history-retention.md) | 工具配置变更历史保留清理 | ONCALL_TOOL_HISTORY_RETENTION_DAYS 默认 365；按 changed_at 独立清理，dry-run/批量；无迁移 |
| [0130](decisions/0130-tool-history-time-index.md) | 工具历史保留清理时间索引 | 新增 `(changed_at, id)` 索引（迁移 0029），避免跨工具清理全表扫描；保留按工具查询索引；无 API 变更 |
| [0131](decisions/0131-session-page-dedup.md) | 会话列表翻页去重 | 游标翻页期间实时聚合/置顶变化可能让已加载会话再次出现在后续页；前端保留首次位置，较新副本覆盖字段，只去重不解决跳过 |

> ADR 的写法：背景 → 方案对比 → 决策 → 后果。面试被问"为什么这么做"时，直接念 ADR。

## 约定

- 让 AI 编码助手参与开发前，先读仓库根目录的 [AGENTS.md](../AGENTS.md)：那里是可执行的约束（硬规则 R1–R13、常见任务 recipe、反模式清单）
- 所有时间戳为 UTC（`timestamptz`），前端本地化显示
- 金额单位为「分」（整数），避免浮点误差
- 事件序号 `seq` 在单个 run 内严格递增，从 1 开始
- 文档与代码不一致时，**以文档为准并提 PR 改代码**（文档是契约）
