# ADR-0002 · 后端选 Python + FastAPI

- 状态：已采纳
- 日期：2026-11-08

## 背景

我后端经验是"参与子模块"级别的 Python / Golang（得物成本中心、玄麟微服务）。
Node.js 我更熟，但本项目要投的是长沙的 AI 应用 / Agent 开发岗。

## 方案对比

| 维度 | Python + FastAPI | Node + Hono/Fastify |
|---|---|---|
| 目标岗位显性要求 | LangChain / LangGraph / FastAPI 高频出现 | 极少出现 |
| Agent 生态 | 最完整（LangGraph、向量库、评测工具） | 需自己拼装 |
| 我的熟练度 | 中低（参与过） | 高 |
| 6 周风险 | 中（3-5 天学习） | 低 |

## 决策

选 **Python 3.12 + FastAPI + Pydantic v2**。

这是一次**主动的岗位池扩张**：用 5 天学习换"能从 Java/前端 池子跨到 AI 应用池子"的资格。长沙 16 条 AI 岗 JD 里 Python 是硬门槛，Node 几乎不出现。

## 学习策略（不用从语法学起）

用"翻译法"把熟悉的 JS 逻辑逐条对照：

| JS | Python |
|---|---|
| `zod` | `Pydantic v2` |
| `Express/Nest 中间件` | FastAPI 依赖注入 / middleware |
| `async/await` | 一样，但注意 `asyncio.timeout` 与协作式取消 |
| `Array.map/filter` | 列表推导 / `filter` |
| 装饰器（TS） | 装饰器（Python，语义类似） |
| `package.json` | `pyproject.toml` + uv |

## 后果

- 正面：直接匹配 JD；Pydantic 让"工具入参校验 + OpenAPI + 前端类型"三者同源
- 负面：类型系统比 TS 弱，需要 mypy 兜底；GIL 下 CPU 密集任务要避开（本项目都是 IO 密集，无影响）
- 缓解：`app/agent`、`app/tools` 开启 mypy 严格模式

## 备注

Node 不是"错"的选择，只是在这个目标市场里性价比低。面试被问到时，回答"选型看岗位池，不选我最熟的"，比辩解更有说服力。
