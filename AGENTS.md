# AGENTS.md

> 面向在本仓库工作的 AI 编码助手（也适用于人类协作者）。
> 这不是背景介绍，**是约束清单**。冲突时以 `docs/` 为准，不以本文为准。

## 0. 30 秒上下文

**OnCall** = 可私有化部署的企业服务台 Agent：查资产 → 验权限 → 调工具 → 开单 → 审批 → 回填。
技术栈：Python 3.12 + FastAPI + LangGraph ｜ React 19 + Vite + Tailwind CSS ｜ PostgreSQL + pgvector ｜ SSE。

当前状态：**骨架与文档完成，RAG / LangGraph 图 / 模型网关 / 评测尚未实现**。
写代码前先确认你要做的是路线图里的哪一天（`docs/10-roadmap-6weeks.md`）。

## 1. 开始前必读（按顺序，别跳）

1. [docs/00-index.md](docs/00-index.md) —— 文档地图
2. [docs/03-api-contract.md](docs/03-api-contract.md) —— **前后端唯一契约**
3. [docs/06-tool-governance.md](docs/06-tool-governance.md) —— 本项目的核心价值
4. [docs/10-roadmap-6weeks.md](docs/10-roadmap-6weeks.md) —— 你该做哪一天的事
5. 对应模块文档：`01` 架构 / `02` 数据 / `04` Agent / `05` RAG / `07` 前端 / `08` 评测 / `09` 部署

**文档是契约。** 文档与代码冲突时：先改文档、再改代码，或明确提出问题；**不要默默改代码**。

## 2. 仓库地图（含禁止事项）

| 路径 | 职责 | 禁止 |
|---|---|---|
| `server/app/api/` | 参数校验、鉴权、调 service、返回/流式 | 放业务规则、写 SQL、拼提示词 |
| `server/app/core/` | 配置、日志、SSE 编码、存储、限流、预算 | 掺业务语义 |
| `server/app/agent/` | 状态机、节点、提示词 | 节点内直接调 HTTP / 写库 / 发事件 |
| `server/app/gateway/` | 模型选择、调用、计量、降级 | 做业务判断 |
| `server/app/tools/` | 工具注册、校验、权限、执行、超时 | 在 MCP server 里重复实现治理 |
| `server/app/rag/` | 解析、切分、索引、检索、引用 | 在业务代码里直接写向量 SQL |
| `server/app/eval/` | 评测集与执行器 | 静默剔除失败用例 |
| `web/src/features/chat/` | 状态机、SSE 客户端、对话 UI | 用 boolean 拼状态 |
| `web/src/features/console/` | 管理后台 | 绕过治理直接调工具 |
| `web/src/components/ui/` | shadcn/ui 组件（源码复制，见 ADR-0008） | 手改样式时绕开设计令牌 |
| `web/src/styles/global.css` | Tailwind 入口与 `@theme` 设计令牌 | 写具体组件的样式 |
| `docs/` | 设计契约 | 与代码不一致却不更新 |

## 3. 命令（不要自己造脚本）

Windows 用 `pwsh -File scripts/dev.ps1 <target>`，其余用 `make <target>`，两者等价。

| 目标 | 作用 |
|---|---|
| `up` / `down` / `logs` | 起停 postgres + redis |
| `install` | `uv sync --all-extras` + `pnpm install` |
| `api` | `uvicorn app.main:app --reload --port 8000` |
| `web` | `vite`（5173，`/api` 已代理到 8000） |
| `fmt` | `ruff format` + `oxfmt` |
| `lint` | `ruff check` + `mypy app` + `oxlint` + `oxfmt --check` |
| `test` | `pytest` + `vitest` |
| `eval` / `seed` | 评测 / 造数据（当前为占位） |

单独跑：

```bash
cd server && uv run pytest -q
cd server && uv run ruff check . && uv run mypy app
cd web && pnpm exec tsc --noEmit && pnpm test && pnpm lint && pnpm format:check
```

## 4. 硬规则（R1–R13，review 时按编号提）

| # | 规则 | 为什么 |
|---|---|---|
| R1 | 事件类型**只增不改**，payload 只加可选字段 | 前端要兼容旧事件；改名等于破坏契约 |
| R2 | 事件**先落库、再推送** | 推送失败不能丢数据；回放依赖事件表 |
| R3 | 工具治理只写在 `tools/registry.py` | 换传输（stdio/HTTP）时不能重复实现 |
| R4 | `api/` 不写业务、不写 SQL | 路由薄层，便于替换传输层 |
| R5 | 节点**不发事件**，由 runtime 统一发 | 避免节点里到处 `yield`，也便于回放 |
| R6 | 金额一律用「分」整数；时间戳一律 UTC | 浮点误差、时区错乱都是线上事故 |
| R7 | `seq` 在单 run 内从 1 递增，**禁止按时间戳排序** | 同毫秒事件会乱序 |
| R8 | 前端遇到未知事件**必须忽略**，不能 throw | 后端加事件时旧前端不能白屏 |
| R9 | 身份字段（`user_id`/`role`/`tenant`…）只能来自服务端会话 | 模型入参里的身份一律拒绝（`RESERVED_ARGS`） |
| R10 | 写操作必须人工审批；写操作只在**声明幂等**后才允许重试 | 重试 = 重复开单 |
| R11 | 写进简历/README 的每个数字都要有口径（怎么测 / 测几次 / 什么条件） | 数字溯源，测不出来就删掉 |
| R12 | 不引入被否决的依赖 | 见第 7 节反模式 |
| R13 | 不提交 `.env`、密钥、真实客户数据 | — |

## 5. 常见任务 recipe

### 5.1 新增一个事件类型

1. 改 [docs/03-api-contract.md](docs/03-api-contract.md)：加 type + payload 表 + 前端动作
2. `server/app/schemas/event.py` → `EventType` 追加
3. `web/src/features/chat/types.ts` → `EventType` 联合追加
4. `web/src/features/chat/machine.ts` → `runtimeReducer` 加分支（**必须先想清楚非法转移**）
5. `web/src/features/chat/machine.test.ts` → 加一条归约测试
6. 若是状态转移触发条件，同步 `TRANSITIONS` 表

### 5.2 新增一个工具

1. 在 `tools/registry.py` 的 `ToolSpec` 里注册（`input_schema` 必填，`timeout_ms` 按工具单独给）
2. 明确 `is_write` / `roles` / `retryable`
3. 决定降级行为，写进 [docs/06-tool-governance.md](docs/06-tool-governance.md) 的降级表
4. `server/tests/test_tools_guard.py` 至少覆盖：权限拒绝、保留字段、写操作挂起（+ 超时路径若适用）
5. 更新文档 8.3 工具清单表

### 5.3 新增一个 Agent 节点

1. 读 [docs/04-agent-design.md](docs/04-agent-design.md) 第 3 节，确认它属于「规则」还是「LLM」
2. 实现为纯函数 `(state, deps) -> dict`，放 `agent/nodes/`
3. 在 `agent/graph.py` 加节点与边；条件边同步 `route_*` 函数
4. **不改变**「8 节点只有 2 个调 LLM」的基线，若要改，先改 `docs/04`

### 5.4 改表结构

1. 改 `server/app/models/`
2. `uv run alembic revision --autogenerate -m "xxx"`，**人工审一遍**（autogenerate 会漏索引/CHECK）
3. 迁移必须写 `downgrade`
4. 同步 [docs/02-data-model.md](docs/02-data-model.md)

### 5.5 改检索参数 / 提示词

必须跑 `make eval` 并与基线对比；回归超过 -3pp 不允许合并（见 `docs/08` 第 6 节）。

## 6. 代码风格

**Python**：ruff（line 100）+ mypy；`app/agent`、`app/tools` 开严格模式；异常在工具边界必须兜住；注释只写「为什么」。
**TypeScript**：`strict: true`；禁 `any`，用 `unknown` + 收窄；状态逻辑写成纯函数以便测试。
**样式**：一律 Tailwind CSS utility class；色值/字号只从 `web/src/styles/global.css` 的 `@theme` 令牌取（`bg-panel`/`text-muted`），不写内联 `style`、不新增 `.oncall-xxx` 全局类。
**组件**：通用组件用 shadcn（`pnpm dlx shadcn@latest add <name>` → `src/components/ui/`），不手写 Dialog/Select/Table；改外观走令牌映射，不改组件主色（ADR-0008）。
**代码约束**：oxc 系（`oxlint` 查问题 + `oxfmt` 格式化），不再使用 Biome；新增 lint 规则改 `web/.oxlintrc.json` 并说明理由。
**提交信息**：`feat(agent): …` / `fix(tools): …` / `docs: …` / `chore: …`。

## 7. 反模式（明确不要做）

| 想做的事 | 为什么不行 | 正确做法 |
|---|---|---|
| 用 `AgentExecutor` 一把梭 | 黑盒，讲不清工具边界 | 自己写节点 + LangGraph 编排 |
| 用 `EventSource` 收流 | 无法带 POST 与鉴权头 | `fetch` + `ReadableStream` |
| 上 LiteLLM 做网关 | 路由/降级/预算正是要讲的设计，不能被配置化 | 自研薄层（~300 行） |
| 让模型判断「这个操作安全」 | 可被提示词注入 | 审批 + 服务端权限判定 |
| 空检索结果直接喂给模型 | 幻觉头号来源 | 兜底话术 + 转人工 + 记 badcase |
| 引入 Milvus / 独立向量集群 | 私有化组件翻倍，5 万 chunk 用不上 | pgvector（见 ADR-0004） |
| 搞 pnpm workspace + turborepo | 6 周项目里边际收益极低 | 两目录各自管依赖，compose 编排 |
| 为了好看加动画/炫技组件 | 时间预算会崩 | 先保三条剧本能演示 |
| 重新拉回 antd / 组件库自带样式 | 与 Tailwind 抢样式优先级，改一处要翻两套文档 | shadcn 组件 + `@theme` 令牌（ADR-0008） |
| 跑 `shadcn add --all`，或改生成组件的硬编码主色 | 一次全加会把用不上的依赖和新 API 带进来；改主色等于长出第二套色板 | 只加需要的组件；颜色改 `global.css` 的令牌映射 |
| 用 CSS Modules / styled-components 写组件样式 | 与 utility 体系并存会产生第二套设计令牌 | Tailwind + `@theme`，见 ADR-0006 |
| 静默跳过失败用例 | 评测失去意义 | 原样展示，写进失败归因 |
| 在简历/README 写测不出的数字 | 被追问就穿 | 口径三件套，测不出就删 |

## 8. 完成标准（DoD）

- [ ] `make lint` 通过（ruff + mypy + oxlint + oxfmt --check）
- [ ] `make test` 通过（pytest + vitest）
- [ ] 涉及接口/事件 → `docs/03-api-contract.md` 已更新
- [ ] 涉及表 → alembic 迁移已生成并人工审过 + `docs/02` 已更新
- [ ] 涉及工具 → 治理测试已加 + `docs/06` 降级表已更新
- [ ] 涉及取舍 → 补一篇 `docs/decisions/`
- [ ] 没有新增 `TODO` 而不写归属里程碑

## 9. 当前待办（按路线图）

| 里程碑 | 事项 | 文件 |
|---|---|---|
| W1 D2 | JWT 鉴权替换 `user_id="u_102"` 占位 | `api/chat.py` |
| W1 D4 | ✅ 已完成：Postgres store + alembic 0001 + `Last-Event-ID` 续传 | `core/store.py`, `migrations/` |
| W1 D5 | 假事件流 → 真实 Agent 运行时 | `agent/demo.py` → `agent/runtime.py` |
| W2 | RAG 全链路 + 评测 v0 | `rag/*`, `eval/*`, `seed/*` |
| W3 | 8 节点图 + 审批闭环 | `agent/graph.py`, `agent/nodes/*` |
| W4 | 模型网关 + 成本看板 | `gateway/*` |
| W5–W6 | 后台四页 + 私有化交付 | `web/src/features/console/*` |

## 10. 不确定时

不要猜。三种选择，按优先级：

1. 查 `docs/`，尤其 `decisions/` 里已记录过的取舍
2. 把问题写成 `docs/decisions/000X-*.md` 的「待定」段落并说明候选方案
3. 直接问人

**宁可停下来问，也不要写一段"看起来能跑但说不清为什么"的代码** —— 这个项目的全部价值就在于每个决策都能讲清楚。
