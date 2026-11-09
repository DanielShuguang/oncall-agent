"""classify 节点：意图识别（规则版，W3 D11）。

W3 还没有模型网关（W4 才接），所以 docs/04 §3 的「小模型兜底」暂不启用：
规则覆盖三类可执行意图，未命中落 `knowledge`（纯 RAG）。

    ticket_create  用户明确要求开单/报修 → 写操作，后面必须审批
    asset_check    涉及设备/硬件 → 先查 CMDB
    knowledge      其余 → 只做检索问答

`incident_type` 仍然是工单分类（hardware|network|software|account|other），
和 `intent` 分开：前者进工单字段，后者决定要不要调工具。
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import AgentState

INTENT_TICKET = "ticket_create"
INTENT_ASSET = "asset_check"
INTENT_KNOWLEDGE = "knowledge"

#: 写操作意图：命中即计划 create_ticket，由治理层挂起等审批（R10）。
#: 只收「明确要开单」的说法；“申请/审批”单独出现时多是政策咨询，交给 RAG。
WRITE_KEYWORDS = ("开单", "报修", "帮我申请", "提交申请", "申请开通")

#: 需要先查资产的关键词。`连不上` 这类泛化词不在此列：
#: VPN/网络问题查资产没有意义，由 RAG 回答。
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


def classify_incident(query: str) -> str:
    lowered = query.lower()
    for incident, keywords in INCIDENT_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return incident
    return "other"


def wants_write(query: str) -> bool:
    return any(keyword in query for keyword in WRITE_KEYWORDS)


def wants_asset(query: str, incident: str) -> bool:
    return incident == "hardware" or any(keyword in query for keyword in ASSET_KEYWORDS)


def classify_intent(query: str, incident: str) -> str:
    if wants_write(query):
        return INTENT_TICKET
    if wants_asset(query, incident):
        return INTENT_ASSET
    return INTENT_KNOWLEDGE


def classify_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：intent / incident_type。"""
    del deps  # 规则节点不需要依赖，签名保持统一便于 W4 换成规则 + 模型兜底
    query = state.get("query", "")
    incident = classify_incident(query)
    return {"intent": classify_intent(query, incident), "incident_type": incident}
