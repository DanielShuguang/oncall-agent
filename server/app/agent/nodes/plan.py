"""plan 节点：决定「查什么 / 做什么」。

W1 D5 是**规则版**：关键词命中即产出工具计划（docs/04 §3 的降级路径）。
W3 D13 换成 LLM + JSON Schema 约束；节点签名不变，只换实现。

注意：这里产出的 args 只能有业务参数，身份字段（owner_id 之外的
user_id/role/tenant）一律不允许出现在计划里（R9）。
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import AgentState

#: 写操作意图：命中即计划 create_ticket，由治理层挂起等审批（R10）。
#: 只收「明确要开单」的说法；“申请/审批”单独出现时多是政策咨询，交给 RAG。
WRITE_KEYWORDS = ("开单", "报修", "帮我申请", "提交申请", "申请开通")

#: 需要先查资产的关键词。`连不上` 这类泛化词不在此列：
#: VPN/网络问题查资产没有意义，W2 起由 RAG 回答，W3 再由 LLM 决定。
ASSET_KEYWORDS = (
    "打印机",
    "电脑",
    "笔记本",
    "台式机",
    "显示器",
    "键盘",
    "鼠标",
    "设备",
    "资产",
    "蓝屏",
    "离线",
)

#: 分类规则，命中顺序即优先级（docs/04 §3 classify 的规则部分）
INCIDENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hardware", ("打印机", "电脑", "笔记本", "显示器", "键盘", "鼠标", "蓝屏", "开机")),
    ("network", ("vpn", "VPN", "断网", "网络", "wifi", "WiFi", "无线", "dns")),
    ("account", ("密码", "账号", "登录", "权限", "认证")),
    ("software", ("软件", "安装", "office", "Office", "驱动", "崩溃", "闪退")),
)


def classify(query: str) -> str:
    for incident, keywords in INCIDENT_RULES:
        if any(keyword in query for keyword in keywords):
            return incident
    return "other"


def wants_write(query: str) -> bool:
    return any(keyword in query for keyword in WRITE_KEYWORDS)


def plan_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：intent / incident_type / plan。"""
    del deps
    query = state.get("query", "")
    incident = classify(query)

    plan: list[dict[str, Any]] = []
    if wants_write(query):
        plan.append(
            {
                "tool": "create_ticket",
                "args": {
                    "title": query[:100],
                    "category": incident,
                    "priority": "P2",
                },
                "reason": "用户要求开单/报修，写操作必须人工审批",
            }
        )
    elif any(keyword in query for keyword in ASSET_KEYWORDS) or incident == "hardware":
        plan.append(
            {
                "tool": "query_cmdb",
                "args": {"owner_id": state.get("user", {}).get("id", "")},
                "reason": "先确认名下资产状态，再给排查建议",
            }
        )

    return {"intent": incident, "incident_type": incident, "plan": plan}
