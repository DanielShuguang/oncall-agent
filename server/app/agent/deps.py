"""运行时依赖（节点与 runtime 共享）。

节点只拿到 `AgentDeps`，不直接碰 HTTP / 数据库 / 事件发送：
- `retriever` 是 RAG 协议实现（内存或 pgvector），节点只调用 `search()`
- 工具执行统一走 `guard`，节点自己不调 handler
- 审批只通过 `approvals` 协议提交/查询，runtime 不碰 SQL
"""

from __future__ import annotations

from dataclasses import dataclass

from app.approvals.types import ApprovalRecorder
from app.rag.retrieve import Retriever
from app.tools.registry import ToolGuard


@dataclass(frozen=True, slots=True)
class AgentDeps:
    guard: ToolGuard
    retriever: Retriever | None = None
    top_k: int = 5
    approvals: ApprovalRecorder | None = None
