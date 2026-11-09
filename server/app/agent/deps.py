"""运行时依赖（节点与 runtime 共享）。

节点只拿到 `AgentDeps`，不直接碰 HTTP / 数据库 / 事件发送：
- `retriever` 是 RAG 协议实现（内存或 pgvector），节点只调用 `search()`
- 工具执行统一走 `guard`，节点自己不调 handler
- 审批只通过 `approvals` 协议提交/查询，runtime 不碰 SQL
"""

from __future__ import annotations

from dataclasses import dataclass

from app.approvals.types import ApprovalRecorder
from app.gateway.types import ModelGateway
from app.rag.retrieve import Retriever
from app.tools.registry import ToolGuard


@dataclass(frozen=True, slots=True)
class AgentDeps:
    guard: ToolGuard
    retriever: Retriever | None = None
    top_k: int = 5
    approvals: ApprovalRecorder | None = None
    #: None = mock 模式，节点走确定性规则；非 None 时 classify/plan 才调模型
    gateway: ModelGateway | None = None
    #: 客户端指定的模型；网关只会路由到已配置的模型
    requested_model: str | None = None
