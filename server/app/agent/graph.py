"""8 节点显式状态机（W3 D11-D15）。

设计见 docs/04-agent-design.md 与 ADR-0012。这里只放**图的形状**——
节点顺序、条件边、节点标题；调度与事件在 `runtime.py`。

为什么 W3 没有直接上 LangGraph：
1. 审批恢复需要"从 act 的同一次调用继续"，LangGraph 的 checkpointer 要额外引入
   `langgraph-checkpoint-postgres`，而我们的审计真相是事件表（R2），两套状态源
   容易对不上；
2. 每个 tool.call 必须在执行**前**推送并落库，节点纯函数 + runtime 统一发事件的
   约束下，用显式转移表反而更容易讲清楚；
3. docs/04 §8 本来就把它列为 LangGraph 卡住时的预案，节点函数两边通用。

条件边只有两条：
    verify --(通过)--> finalize
    verify --(失败且还能重规划)--> plan
    approve --(通过)--> act
"""

from __future__ import annotations

from app.agent.state import MAX_REPLAN

NODES: tuple[str, ...] = (
    "intake",
    "classify",
    "retrieve",
    "plan",
    "act",
    "verify",
    "approve",
    "finalize",
)

NODE_TITLES: dict[str, str] = {
    "intake": "理解问题",
    "classify": "识别意图",
    "retrieve": "检索知识库",
    "plan": "制定处理计划",
    "act": "调用工具",
    "verify": "校验结果",
    "approve": "确认审批决议",
    "finalize": "组织回答",
}

#: 顺序边；act/verify/approve 的分支由 `next_node` 处理
SEQUENTIAL_EDGES: dict[str, str] = {
    "intake": "classify",
    "classify": "retrieve",
    "retrieve": "plan",
    "plan": "act",
}

#: 恢复执行时从 approve 开始（人工节点已经在 approve 接口里完成）
RESUME_ENTRY = "approve"


def next_node(node: str, *, verify_ok: bool = True, replan_count: int = 0) -> str | None:
    """返回下一节点；None 表示终态。

    `replan_count` 由 verify 节点维护，这里只做防御性判断：即使调用方传了
    不一致的组合，也不会无限重规划。
    """
    if node == "verify":
        if verify_ok:
            return "finalize"
        return "plan" if replan_count <= MAX_REPLAN else "finalize"
    if node == "act":
        return "verify"
    if node == "approve":
        return "act"
    if node == "finalize":
        return None
    return SEQUENTIAL_EDGES.get(node)
