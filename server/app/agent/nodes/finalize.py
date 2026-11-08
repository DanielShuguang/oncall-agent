"""finalize 节点：规则拼装回答。

W2 接入 RAG 后，引用与「无引用不回答」的校验放在这里（docs/04 §5）；
W1 只有工具结果，没有知识库，所以 citations 为空。
"""

from __future__ import annotations

from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import AgentState

_BODY: dict[str, str] = {
    "hardware": (
        "打印机/外设离线通常先排查这三点："
        "1）确认设备与电脑在同一网段；"
        "2）在服务里重启 Print Spooler；"
        "3）删除设备后重新添加打印机。"
    ),
    "network": (
        "先确认是否只有你这台设备断网：1）重新连接 VPN；2）把 DNS 切到内网 DNS；3）重启网络适配器。"
    ),
    "account": (
        "账号类问题建议先自助处理：1）在 SSO 门户重置密码；2）确认账号未被锁定；"
        "3）仍失败则申请权限复核。"
    ),
    "software": (
        "软件问题先确认版本与权限：1）用管理员权限重新安装；2）清理旧版本残留；"
        "3）驱动从内网软件库获取。"
    ),
    "other": (
        "我暂时没有查到可直接执行的处理方案。可以补充设备型号与报错信息，"
        "或让我帮你开一张工单转 IT 服务台。"
    ),
}

_TAIL = "如果以上步骤仍不能解决，我可以帮你开一张报修工单。"


def _first_tool(state: AgentState, tool: str) -> dict[str, Any] | None:
    for item in state.get("tool_results", []):
        if item.get("tool") == tool:
            return item
    return None


def compose_answer(state: AgentState) -> str:
    incident = state.get("incident_type", "other")
    asset_call = _first_tool(state, "query_cmdb")
    asset = asset_call.get("result") if asset_call is not None else None

    parts: list[str] = []
    if isinstance(asset, dict):
        parts.append(
            f"已确认你名下的 {asset.get('model', '设备')}"
            f"（{asset.get('asset_id', '-')}）状态为 {asset.get('status', '未知')}。"
        )
    elif asset_call is not None:
        # 工具失败不中断 run，按 docs/06 §6 的降级话术继续给建议
        parts.append("资产信息暂时没查到（数据可能过期），我按通用步骤给你建议。")

    parts.append(_BODY.get(incident, _BODY["other"]))
    if incident != "other":
        parts.append(_TAIL)
    return "".join(parts)


def finalize_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：追加一条 assistant 消息。"""
    del deps
    answer = compose_answer(state)
    messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
    return {"messages": messages}
