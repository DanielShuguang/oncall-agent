# ADR-0012 · W3 用显式转移表调度 8 节点，LangGraph 延后

- 状态：已采纳（W3 D11–D15）
- 日期：2026-11-09
- 相关：[04-Agent 设计](../04-agent-design.md)、[ADR-0003](0003-langgraph.md)、[10-路线图](../10-roadmap-6weeks.md)

## 背景

[ADR-0003](0003-langgraph.md) 定的是 LangGraph 做编排，docs/04 §7 也给了节点图示例；
W1 先落地了手写调度器（`agent/runtime.py`），当时约定 W3 换成 LangGraph 8 节点图。

W3 真正动手时，阻塞点不是"图怎么画"，而是**审批恢复**：

1. 写操作在 `act` 挂起，run 要停在 `awaiting_approval` 且可以恢复。
   LangGraph 的常规做法是 checkpointer（`langgraph-checkpoint-postgres`）；
   但本项目的审计真相是 `run_events` 事件表（R2），checkpointer 会引入第二套状态源。
2. 恢复只能重放**挂起的那一次 act 调用**。审批人看到的参数快照必须与执行参数一致，
   不能因为等待期间知识库/配置变化而重跑 `intake → plan`。
3. 每个 `tool.call` 必须在执行前落库并推送；节点是纯函数、事件由 runtime 统一发（R5）。
   在 LangGraph 里要满足"执行前发事件"，要么让节点发事件（违反 R5），
   要么在节点外面包一层事件队列，代码复杂度高于收益。
4. `langgraph` 属于可选 `agent` extra，默认 `uv sync` 不装；为了 W3 把它变成核心依赖，
   会让"最小可运行"安装体积和 CI 都变重，而 W3 验收并不要求某个框架。

docs/04 §8 本来就写了退路：

> 如果 LangGraph 卡住，退回手写：转移表放 `agent/transitions.py`，
> 和 LangGraph 版本共用节点函数 —— 两条路只换调度器，不换节点。

## 决策

1. W3 使用**显式转移表**（落在 `server/app/agent/graph.py`）：8 个节点、两条条件边
   （`verify → finalize|plan`、`approve → act`），没有隐藏的自动转移。
2. 节点函数保持 `(state, deps) -> dict` 的纯函数签名；`act` 因为要逐次发
   `tool.call` / `tool.result`，执行循环留在 runtime（计划仍由 `plan` 节点产出，
   能不能执行仍由 `ToolGuard` 决定）。
3. 审批恢复由 `agent/runtime.py::resume()` 从 `approvals.state` 快照执行；
   审批存储与 runtime 之间只用 `ApprovalRecorder` 协议。
4. `langgraph` / `langchain-core` 继续留在可选 `agent` extra；W4 接入模型网关时
   再评估是否用它替换调度层 —— 届时节点函数可以直接复用。

## 被否决的方案

| 方案 | 否决原因 |
|---|---|
| W3 硬上 LangGraph + Postgres checkpointer | 多一套状态源；审批恢复要校验事件表与 checkpoint 一致，出错面更大 |
| 让节点自己发事件 | 违反 R5；回放与测试都会变难，节点不再可单测 |
| 恢复时重跑整条链 | 审批参数与执行参数可能不一致；检索/工具副作用也会重放 |
| 直接删除 `graph.py` 占位 | 图的结构（节点顺序/条件边）需要可读、可测，保留为显式表更诚实 |

## 后果

- 正面：审批闭环可以在一个进程内讲清楚；节点可单测（`tests/test_agent_graph.py`）；
  事件顺序完全由 runtime 控制；不增加默认安装体积。
- 负面：没有 LangGraph 的 checkpointer / 中断恢复能力；以后要接多 Agent、子图、
  人工中断等能力时需要迁移。
- 迁移路径：节点函数与 `NODES` / `next_node` 已按图定义，换 LangGraph 时只改
  `runtime.py` 的调度层；审批恢复仍以事件表为准。
- 面试口径：**"框架是为了少写调度代码，不是为了把状态藏起来"**；
  这个项目的状态真相是事件表，审批恢复必须能解释每一次执行。
