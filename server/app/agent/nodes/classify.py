"""classify 节点：意图识别（规则优先 + 小模型兜底，W4 D16）。

规则覆盖三类可执行意图；只有「规则完全没命中」的模糊输入才走小模型
（`ONCALL_MOCK_MODE=false` 时）。模型只允许把模糊输入判成
`knowledge` / `asset_check`，**不允许**凭模糊文本升级成 `ticket_create`：
开单是写操作，必须由用户明确表达（R10）。
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.nodes.json_utils import extract_json_object
from app.agent.prompts import load_prompt
from app.agent.state import AgentState
from app.core.logging import get_logger
from app.gateway.types import (
    BudgetExceeded,
    ChatMessage,
    MeteringError,
    ModelUnavailable,
    ModelUsage,
    Purpose,
)

log = get_logger(__name__)

INTENT_TICKET = "ticket_create"
INTENT_ASSET = "asset_check"
INTENT_KNOWLEDGE = "knowledge"

INTENTS = {INTENT_TICKET, INTENT_ASSET, INTENT_KNOWLEDGE}
INCIDENT_TYPES = {"hardware", "network", "software", "account", "other"}

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
    "平板",
    "设备",
    "资产",
    "蓝屏",
    "离线",
)

#: 政策/流程类问法：句子里出现设备名也可能是在问知识（"公司电脑保修几年"），
#: 不能路由到资产查询。写操作关键词优先级更高，先判断。
POLICY_MARKERS = (
    "政策",
    "流程",
    "规定",
    "新员工",
    "需要审批",
    "怎么申请",
    "怎么开通",
    "在哪",
)

#: 「保修」本身既可能是政策问题，也可能是查我这台设备的保修状态；
#: 出现个人指代或故障症状时按资产处理（多跳用例需要 query_cmdb）。
PERSONAL_OR_PROBLEM_MARKERS = (
    "我的",
    "我这",
    "本人",
    "坏",
    "不耐用",
    "闪",
    "卡",
    "蓝屏",
    "进水",
    "开不了机",
    "没声音",
    "失灵",
    "鼓包",
    "脱机",
    "没墨",
    "漏粉",
    "装不上",
    "连不上",
    "断",
)

#: 分类规则，命中顺序即优先级（docs/04 §3 classify 的规则部分）。
#: software 放在 account 前：「软件安装权限」主领域是软件，不是账号。
INCIDENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "hardware",
        ("打印机", "电脑", "笔记本", "台式机", "显示器", "键盘", "鼠标", "蓝屏", "开机"),
    ),
    (
        "network",
        ("vpn", "VPN", "断网", "网络", "wifi", "WiFi", "无线", "dns", "代理", "上网"),
    ),
    ("software", ("软件", "安装", "office", "Office", "驱动", "崩溃", "闪退")),
    ("account", ("密码", "账号", "登录", "权限", "认证")),
)

#: 模糊输入至少这么长才值得花一次模型调用；"你好" 之类直接按规则走
MODEL_FALLBACK_MIN_CHARS = 6


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


def asks_policy(query: str) -> bool:
    """问政策/流程，而不是报修或查我这台设备的保修状态。"""
    if any(marker in query for marker in POLICY_MARKERS):
        return True
    # 只问「保修多久」但没有任何个人指代/故障症状 → 政策问题
    return "保修" in query and not any(marker in query for marker in PERSONAL_OR_PROBLEM_MARKERS)


def classify_intent(query: str, incident: str) -> str:
    if wants_write(query):
        return INTENT_TICKET
    # 先排除政策问法：「公司电脑保修几年」虽含设备名，但应走 RAG
    if asks_policy(query):
        return INTENT_KNOWLEDGE
    if wants_asset(query, incident):
        return INTENT_ASSET
    return INTENT_KNOWLEDGE


def needs_model(query: str) -> bool:
    """规则无法判断时才调模型：没有任何关键词命中，且输入足够长。"""
    return (
        len(query.strip()) >= MODEL_FALLBACK_MIN_CHARS
        and not wants_write(query)
        and classify_incident(query) == "other"
        and not any(keyword in query for keyword in ASSET_KEYWORDS)
    )


def parse_classification(text: str) -> tuple[str, str] | None:
    """解析模型 JSON；非法输入返回 None，由调用方保留规则结果。"""
    payload = extract_json_object(text)
    if payload is None:
        return None
    intent = payload.get("intent")
    incident = payload.get("incident_type")
    if not isinstance(intent, str) or intent not in INTENTS:
        return None
    if not isinstance(incident, str) or incident not in INCIDENT_TYPES:
        return None
    # 模糊输入不允许升级为写操作（R10）
    if intent == INTENT_TICKET:
        intent = INTENT_KNOWLEDGE
    return intent, incident


async def classify_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：intent / incident_type / classified_by / usage。"""
    query = state.get("query", "")
    incident = classify_incident(query)
    intent = classify_intent(query, incident)
    usage = ModelUsage()
    source = "rule"

    if deps.gateway is not None and needs_model(query):
        user = state.get("user", {})
        try:
            completion = await deps.gateway.chat(
                [
                    ChatMessage(role="system", content=load_prompt("classify")),
                    ChatMessage(role="user", content=query),
                ],
                purpose=Purpose.CLASSIFY,
                run_id=str(state.get("run_id", "")),
                step="classify",
                user_id=str(user.get("id", "")),
                spent_cents=ModelUsage.from_dict(state.get("usage")).cost_cents,
                max_tokens=120,
                json_mode=True,
                requested_model=deps.requested_model,
            )
        except BudgetExceeded:
            raise
        except (ModelUnavailable, MeteringError) as exc:
            log.warning("classify_model_fallback", run_id=state.get("run_id"), error=str(exc))
        else:
            usage = usage.add(completion)
            parsed = parse_classification(completion.text)
            if parsed is not None:
                intent, incident = parsed
                source = "llm"

    return {
        "intent": intent,
        "incident_type": incident,
        "classified_by": source,
        "usage": usage.as_dict(),
    }
