"""finalize 节点：拼装回答 + 引用（W2 D9）。

规则：
1. 有检索结果 → 抽取式回答，每条引用标注 `[1] [2]`，并只保留真正用到的引用
2. 无检索结果 / 低于阈值 → 固定兜底话术，不生成、不臆造（docs/05 §5.4）
3. 工具结果（资产状态 / 已创建的工单）作为前缀，工具失败不中断回答

W3 接模型后，这里保留「无引用不回答」的校验：模型给出的引用必须来自
本次 `retrieved`，否则丢弃该句并降级为兜底（docs/04 §5）。
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.deps import AgentDeps
from app.agent.state import AgentState
from app.rag.text import tokenize

MAX_CITATIONS = 3
MAX_SENTENCE_CHARS = 180
#: Markdown 列表标记：回答自己会加 "1. "，正文里原有的编号要去掉，否则出现 "1. 2. …"
_LIST_MARKER = re.compile(r"^(?:\d+[.)]|[-*+•])\s+")

REFUSAL = (
    "知识库里没有检索到可直接引用的处理方法。"
    "可以补充设备型号与报错信息，或让我帮你开一张工单转 IT 服务台。"
)
_TAIL = "如果以上步骤仍不能解决，我可以帮你开一张报修工单。"


def _first_tool(state: AgentState, tool: str) -> dict[str, Any] | None:
    for item in state.get("tool_results", []):
        if item.get("tool") == tool:
            return item
    return None


def _sentences(text: str) -> list[str]:
    # Markdown 里一行可能只是软换行；先接回整句，列表项（- / 1.）保留边界
    normalized = re.sub(r"\n(?![ \t]*(?:[-*+]|\d+\.)\s)", "", text.replace("\r", ""))
    for separator in ("。", "！", "？", "!", "?", "；", ";"):
        normalized = normalized.replace(separator, "\n")
    lines = (_LIST_MARKER.sub("", line.strip()).strip() for line in normalized.splitlines())
    return [line for line in lines if line]


def _best_sentence(content: str, query_tokens: set[str]) -> str:
    candidates = _sentences(content)
    if not candidates:
        return content.strip()[:MAX_SENTENCE_CHARS]

    def weight(token: str) -> float:
        # 型号/错误码/数字单位（P0、25MB）比单字更能决定答案是否命中
        if token.isascii():
            return 3.0
        return 2.0 if len(token) >= 2 else 1.0

    total = sum(weight(token) for token in query_tokens) or 1.0
    best = candidates[0]
    best_score = -1.0
    for sentence in candidates:
        overlap = query_tokens & set(tokenize(sentence))
        score = sum(weight(token) for token in overlap) / total
        # 太短的句子信息量不足，同分时优先信息更完整的
        if 10 <= len(sentence) <= MAX_SENTENCE_CHARS:
            score += 0.01
        if score > best_score:
            best, best_score = sentence, score
    if len(best) > MAX_SENTENCE_CHARS:
        best = best[:MAX_SENTENCE_CHARS].rstrip() + "…"
    return best


def _asset_prefix(state: AgentState) -> str | None:
    asset_call = _first_tool(state, "query_cmdb")
    result = asset_call.get("result") if asset_call is not None else None
    if asset_call is None:
        return None
    assets = result.get("assets") if isinstance(result, dict) else None
    if not isinstance(assets, list):
        # 工具失败不中断 run，按 docs/06 §6 的降级话术继续给建议
        return "资产信息暂时没查到（数据可能过期），我按通用步骤给你建议。"
    if not assets:
        return "你名下暂时没有查到资产记录（CMDB 里没有登记），我按通用步骤给你建议。"
    if len(assets) == 1 and isinstance(assets[0], dict):
        asset = assets[0]
        return (
            f"已确认你名下的 {asset.get('model', '设备')}"
            f"（{asset.get('asset_id', '-')}）状态为 {asset.get('status', '未知')}。"
        )

    def describe(item: object) -> str:
        if not isinstance(item, dict):
            return "设备"
        return (
            f"{item.get('model', '设备')}"
            f"（{item.get('asset_id', '-')}，{item.get('status', '未知')}）"
        )

    shown = "、".join(describe(item) for item in assets[:3])
    if len(assets) <= 3:
        return f"已确认你名下 {len(assets)} 台资产：{shown}。"
    return f"已确认你名下 {len(assets)} 台资产，例如：{shown}。"


def _ticket_prefix(state: AgentState) -> str | None:
    call = _first_tool(state, "create_ticket")
    ticket = call.get("result") if call is not None else None
    if isinstance(ticket, dict):
        return (
            f"已为你创建工单 {ticket.get('id', '-')}"
            f"（{ticket.get('priority', 'P2')}）：{ticket.get('title', '报修')}。"
        )
    if call is not None:
        return "工单没有创建成功，请手动提交或联系 IT 服务台。"
    return None


_TICKET_STATUS_LABELS = {
    "open": "待处理",
    "in_progress": "处理中",
    "resolved": "已解决",
    "closed": "已关闭",
}


def _tickets_answer(state: AgentState) -> str | None:
    """用 query_tickets 的结果直接回答「我的工单到哪了」。

    自述数据以账本/工单表为准，不再拼知识库步骤：用户问的是自己那张单的
    状态，检索到的「如何报修」流程反而是噪声。
    """
    call = _first_tool(state, "query_tickets")
    if call is None:
        return None
    result = call.get("result")
    tickets = result.get("tickets") if isinstance(result, dict) else None
    if not isinstance(tickets, list):
        return "工单信息暂时没查到，请稍后重试或联系 IT 服务台。"
    if not tickets:
        return "你名下暂时没有查到工单。"
    # 工具允许 limit 到 20，回答只列最近 5 张；头部按实际展示数量说，别声称列了 20 张。
    shown = [ticket for ticket in tickets[:5] if isinstance(ticket, dict)]
    if not shown:
        return "工单信息暂时没查到，请稍后重试或联系 IT 服务台。"
    if len(shown) < len(tickets):
        header = f"你名下最近有 {len(tickets)} 张工单，先列最近 {len(shown)} 张："
    else:
        header = f"你名下最近有 {len(tickets)} 张工单："
    lines = [header]
    for ticket in shown:
        status = str(ticket.get("status") or "")
        status_label = _TICKET_STATUS_LABELS.get(status, status or "未知")
        created = str(ticket.get("created_at") or "")[:10]
        suffix = f"（{created}）" if created else ""
        title = str(ticket.get("title") or "未命名")[:60]
        lines.append(
            f"- {ticket.get('id', '-')}（{status_label} / "
            f"{ticket.get('priority', 'P2')}）：{title}{suffix}"
        )
    return "\n".join(lines) + "\n"


def _select_hits(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """选出最多 3 条引用：先保每篇文档的最佳切片，再用高分切片补满。

    只看分数取 Top-3 会出现两个问题：
    - 多跳问题（打印机过保）的保修文档排第 4，被同文档的 3 个切片挤掉
    - 噪声文档碰巧词面重合，被当作第 3 条引用
    """
    if not retrieved:
        return []
    # 归档文档只用于召回对照，不能进引用，也不能参与阈值计算：
    # 旧版本文档常因词面重合拿到最高分，一旦用它算 threshold，
    # 在用的文档会被整体压掉（W6 审阅发现的边界）。
    usable = [hit for hit in retrieved if "归档" not in str(hit.get("title", ""))]
    if not usable:
        return []
    top_score = max(float(hit.get("score", 0.0)) for hit in usable)
    threshold = top_score * 0.8
    best_by_document: dict[str, dict[str, Any]] = {}
    for hit in usable:
        document_id = str(hit.get("document_id", ""))
        if document_id not in best_by_document:
            best_by_document[document_id] = hit
    selected = [
        hit for hit in best_by_document.values() if float(hit.get("score", 0.0)) >= threshold
    ]
    selected.sort(key=lambda hit: -float(hit.get("score", 0.0)))
    selected = selected[:MAX_CITATIONS]

    chosen = {int(hit.get("chunk_id", 0)) for hit in selected}
    primary_doc = str(selected[0].get("document_id", "")) if selected else ""
    for hit in usable:
        if len(selected) >= MAX_CITATIONS:
            break
        chunk_id = int(hit.get("chunk_id", 0))
        if chunk_id in chosen:
            continue
        score = float(hit.get("score", 0.0))
        # 补位不能为了凑满 3 条引入低分噪声（W6 D26 实测 cite_acc 只有 89%）。
        # 同一篇文档的后续步骤放宽到 0.6：排查类答案需要覆盖不同步骤；
        # 跨文档仍需过 0.8 阈值，否则多跳问题会把无关文档当第二证据。
        floor = top_score * 0.6 if str(hit.get("document_id", "")) == primary_doc else threshold
        if score < floor:
            continue
        selected.append(hit)
        chosen.add(chunk_id)
    # 不按分数重排：跨文档的最佳切片要保留在引用里（多跳问题的另一半证据），
    # 同文档的高分切片只用于补满剩余位置。
    return selected[:MAX_CITATIONS]


def compose_answer(state: AgentState) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = []
    prefix = _asset_prefix(state)
    if prefix:
        parts.append(prefix)
    ticket_prefix = _ticket_prefix(state)
    if ticket_prefix:
        parts.append(ticket_prefix)
    tickets_answer = _tickets_answer(state)
    if tickets_answer is not None:
        parts.append(tickets_answer)
        # 查自己工单：以工具结果为准，不再用知识库步骤凑答案，也不产生引用
        return "".join(parts), []

    retrieved = state.get("retrieved", [])
    citation_by_chunk = {
        int(citation["chunk_id"]): citation
        for citation in state.get("citations", [])
        if isinstance(citation, dict) and "chunk_id" in citation
    }
    # 追问的上下文查询（上一轮问题 + 本轮）用来挑句子：只说"那怎么办"时，
    # 单靠本轮 token 选出来的句子和问题毫无关系（ADR-0020）
    query_tokens = set(tokenize(state.get("context_query") or state.get("query", "")))

    if not retrieved:
        parts.append(REFUSAL)
        return "".join(parts), []

    selected = _select_hits(retrieved)
    used: list[dict[str, Any]] = []
    parts.append("根据内部知识库，建议按以下步骤处理：\n")
    for index, hit in enumerate(selected, start=1):
        content = str(hit.get("content", "")).strip()
        if not content:
            continue
        sentence = _best_sentence(content, query_tokens)
        parts.append(f"{index}. {sentence} [{index}]\n")
        citation = citation_by_chunk.get(int(hit.get("chunk_id", 0)))
        if citation is not None:
            used.append(citation)

    if not used:
        # 检索有结果但引用对不上：宁可拒答，也不输出不可溯源的内容
        return REFUSAL, []

    parts.append(_TAIL)
    return "".join(parts), used


def finalize_node(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """返回 state 增量：追加一条 assistant 消息 + 本次引用。"""
    del deps
    answer, citations = compose_answer(state)
    messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
    return {"messages": messages, "citations": citations}
