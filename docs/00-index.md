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
| — | [decisions/](decisions/) | 5 篇 ADR：为什么 React / Python / LangGraph / pgvector / SSE | 面试前重读 |

## ADR（Architecture Decision Record）

| 编号 | 决策 | 一句话结论 |
|---|---|---|
| [0001](decisions/0001-react-over-vue.md) | 前端框架 | React 19，因为差异化在运行时不在框架，选生态更厚的一侧 |
| [0002](decisions/0002-python-fastapi.md) | 后端语言 | Python，因为目标岗位的显性要求，用 5 天学习换一个岗位池 |
| [0003](decisions/0003-langgraph.md) | Agent 编排 | 先手写 1 天 loop，再换 LangGraph，为 checkpoint 与可视化 |
| [0004](decisions/0004-pgvector.md) | 向量存储 | pgvector，5 万 chunk 量级下私有化组件最少 |
| [0005](decisions/0005-sse.md) | 流式协议 | SSE，单向 + 内网代理友好 + `Last-Event-ID` 原生续传 |

> ADR 的写法：背景 → 方案对比 → 决策 → 后果。面试被问"为什么这么做"时，直接念 ADR。

## 约定

- 让 AI 编码助手参与开发前，先读仓库根目录的 [AGENTS.md](../AGENTS.md)：那里是可执行的约束（硬规则 R1–R13、常见任务 recipe、反模式清单）
- 所有时间戳为 UTC（`timestamptz`），前端本地化显示
- 金额单位为「分」（整数），避免浮点误差
- 事件序号 `seq` 在单个 run 内严格递增，从 1 开始
- 文档与代码不一致时，**以文档为准并提 PR 改代码**（文档是契约）
