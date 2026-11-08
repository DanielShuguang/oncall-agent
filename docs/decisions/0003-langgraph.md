# ADR-0003 · Agent 编排：先手写 loop，再用 LangGraph

- 状态：已采纳
- 日期：2026-11-08

## 背景

Agent 编排有三条路：全手写、LangChain 的 `AgentExecutor`、LangGraph。

## 方案对比

| 方案 | 优点 | 缺点 |
|---|---|---|
| 全手写 while loop | 完全可控，理解本质 | 无持久化、无可视化，重启即丢 |
| `AgentExecutor` | 开箱即用 | **黑盒**，问"你怎么控制工具边界"答不了 |
| LangGraph | checkpoint 持久化、显式图、可视化 | 学习成本、抽象泄漏 |

## 决策

**D5 先手写 1 天 loop，D11 换 LangGraph。**

理由：

1. 手写一遍才能真正讲清"Agent = while + state + 工具分发"——这是面试的核心认知，念不出来就是背的
2. LangGraph 的价值点是 **checkpointer**（断点续跑免费拿到）和**显式图**（调试与演示），不是"更高级"
3. 明确不用 `AgentExecutor`：工具治理必须在自己的代码里，黑盒无法回答"模型能不能直接写库"

## 实现约束

- 节点函数与调度器解耦：`nodes/*.py` 是纯函数（state → state_delta），LangGraph 与手写调度器共用
- 手写调度器当前在 `agent/runtime.py`（W1 D5）；W3 拆出 `agent/simple_runner.py`，作为 LangGraph 卡住时的 fallback，与 LangGraph 共用节点
- 节点只做业务，不发事件；事件由 `agent/runtime.py` 统一发出（避免节点里到处 `yield`）

## 后果

- 正面：断点续跑、状态可视化、评测可复现
- 负面：多一层依赖与抽象；LangGraph 版本升级可能破坏 API
- 缓解：pin 版本；节点逻辑不依赖 LangGraph 类型（只用 `TypedDict`）

## 面试话术

> 我先手写过一遍，知道它就是 while 循环加状态机。换 LangGraph 是为了 checkpoint 和可视化调试，不是因为它能替我做决策。节点还是我自己写的，工具边界还是我自己控的。
