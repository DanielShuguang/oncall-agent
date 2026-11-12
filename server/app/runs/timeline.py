"""历史会话的只读运行过程投影（ADR-0035）。

事件仍是唯一真相：这里只把 `tool.call` / `tool.result` 与
`approval.required` / `approval.resolved` 合并成前端可渲染的短列表。
不落库、不回写，所以改渲染或加字段都不需要迁移。

两处刻意的取舍：

- **不返回 `resolved_by` / `scope`**：审批人是谁属于内部治理信息，历史回放
  只需要「批没批、为什么」，不需要暴露同事身份。
- **没有时间戳的事件不猜**：`tool.result` 缺 `duration_ms` 就留空，不用
  event.ts 反推耗时；回放展示的是当时记录下来的值。
"""

from __future__ import annotations

from typing import Any

from app.schemas.event import EventType, RunEvent

MAX_TIMELINE_ITEMS = 20


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int(value: Any) -> int | None:
    # bool 是 int 的子类；duration/attempts 为 True 是脏数据，不能当 1
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def build_timeline(events: list[RunEvent]) -> tuple[list[dict[str, Any]], bool]:
    """把一条 run 的事件折叠成工具调用与审批列表。

    返回 `(items, truncated)`；超过 `MAX_TIMELINE_ITEMS` 时只保留前 N 项并标记，
    不静默丢弃（调用方在响应里回 `timeline_truncated`）。
    """
    items: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    approvals: dict[str, dict[str, Any]] = {}

    for event in events:
        payload = event.payload
        if event.type is EventType.TOOL_CALL:
            call_id = _text(payload.get("call_id"))
            tool = _text(payload.get("tool"))
            if call_id is None or tool is None:
                continue
            tool_item: dict[str, Any] = {
                "kind": "tool",
                "seq": event.seq,
                "call_id": call_id,
                "tool": tool,
                "args": _mapping(payload.get("args")),
                "write": bool(payload.get("write", False)),
                "status": "running",
            }
            items.append(tool_item)
            tools[call_id] = tool_item
        elif event.type is EventType.TOOL_RESULT:
            call_id = _text(payload.get("call_id"))
            result_item = tools.get(call_id) if call_id else None
            if result_item is None:
                # 没有对应 tool.call 的孤儿结果不补卡片：宁可少展示，也不造一条
                # 没有入参的假记录
                continue
            result_item["status"] = _text(payload.get("status")) or "unknown"
            if payload.get("result") is not None:
                result_item["result"] = payload["result"]
            error = _text(payload.get("error"))
            if error is not None:
                result_item["error"] = error
            error_kind = _text(payload.get("error_kind"))
            if error_kind is not None:
                result_item["error_kind"] = error_kind
            duration_ms = _positive_int(payload.get("duration_ms"))
            if duration_ms is not None:
                result_item["duration_ms"] = duration_ms
            attempts = _positive_int(payload.get("attempts"))
            if attempts is not None:
                result_item["attempts"] = attempts
        elif event.type is EventType.APPROVAL_REQUIRED:
            approval_id = _text(payload.get("approval_id"))
            tool = _text(payload.get("tool"))
            if approval_id is None or tool is None:
                continue
            approval_item: dict[str, Any] = {
                "kind": "approval",
                "seq": event.seq,
                "approval_id": approval_id,
                "tool": tool,
                "args": _mapping(payload.get("args")),
                "risk_level": _text(payload.get("risk_level")) or "medium",
                "reason": _text(payload.get("reason")),
                "expires_at": _text(payload.get("expires_at")),
                "status": "pending",
            }
            items.append(approval_item)
            approvals[approval_id] = approval_item
        elif event.type is EventType.APPROVAL_RESOLVED:
            approval_id = _text(payload.get("approval_id"))
            resolved_item = approvals.get(approval_id) if approval_id else None
            if resolved_item is None:
                continue
            resolved_item["status"] = _text(payload.get("status")) or "unknown"
            resolved_item["resolved_at"] = event.ts.isoformat()
            reason = _text(payload.get("reason"))
            if reason is not None:
                resolved_item["decision_reason"] = reason

    return items[:MAX_TIMELINE_ITEMS], len(items) > MAX_TIMELINE_ITEMS


__all__ = ["MAX_TIMELINE_ITEMS", "build_timeline"]
