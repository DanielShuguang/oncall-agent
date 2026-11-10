"""测试夹具：默认用内存 store，不碰真库；Postgres 集成测试单独跳过。

所有请求默认带合法 JWT（W1 D2）：身份来自服务端 token，不再有 `u_102` 占位。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.approvals.store import InMemoryApprovalStore, get_approval_store
from app.budgets.policy import UserBudgetPolicy, set_user_budget_policy
from app.budgets.store import InMemoryUserBudgetStore
from app.core.limits import (
    InMemoryBudgetLedger,
    InMemoryRateLimiter,
    InMemoryUserBudgetLedger,
    set_budget_ledger,
    set_rate_limiter,
    set_user_budget_ledger,
)
from app.core.store import InMemoryRunStore, get_store
from app.gateway.meter import InMemoryModelCallStore, set_model_call_store
from app.main import app
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase
from app.rag.service import set_knowledge_base
from app.tools.policy import InMemoryToolSettingStore, ToolPolicy, set_tool_policy
from app.tools.tickets import InMemoryTicketRepository, set_ticket_repository
from tests.support import auth_headers


@pytest.fixture
def mem_store() -> InMemoryRunStore:
    return InMemoryRunStore()


@pytest.fixture(autouse=True)
def memory_kb() -> AsyncIterator[KnowledgeBase]:
    """测试一律用内存知识库：不碰 pgvector，也不让上传文档跨用例污染。"""
    kb = KnowledgeBase(
        store=MemoryKnowledgeStore(),
        embedder=HashingEmbedder(),
        auto_seed=True,
    )
    set_knowledge_base(kb)
    yield kb
    set_knowledge_base(None)


@pytest.fixture(autouse=True)
def mem_approvals() -> AsyncIterator[InMemoryApprovalStore]:
    """审批默认落内存：测试不碰 approvals 表，也不跨用例污染。"""
    store = InMemoryApprovalStore()
    app.dependency_overrides[get_approval_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_approval_store, None)


@pytest.fixture(autouse=True)
def mem_tickets() -> AsyncIterator[InMemoryTicketRepository]:
    repo = InMemoryTicketRepository()
    set_ticket_repository(repo)
    yield repo
    set_ticket_repository(None)


@pytest.fixture(autouse=True)
def mem_tool_settings() -> Iterator[ToolPolicy]:
    """工具覆盖默认落内存：管理接口测试不碰 tool_settings 表。"""
    policy = ToolPolicy(InMemoryToolSettingStore(), ttl_s=0)
    set_tool_policy(policy)
    yield policy
    set_tool_policy(None)


@pytest.fixture(autouse=True)
def mem_model_calls() -> AsyncIterator[InMemoryModelCallStore]:
    """计量默认落内存：不碰 model_calls 表，也不跨用例串数据。"""
    store = InMemoryModelCallStore()
    set_model_call_store(store)
    yield store
    set_model_call_store(None)


@pytest.fixture(autouse=True)
def mem_limits() -> Iterator[None]:
    """限流/预算默认给足额度；需要边界的用例自己 set 更小的实现。

    用户预算的覆盖表也换成内存实现（ADR-0026）：默认 0 = 不限，
    否则测试会在没有 Postgres 的环境里读 `user_budgets` 表。
    """
    set_rate_limiter(InMemoryRateLimiter(limit=0))
    set_budget_ledger(InMemoryBudgetLedger(limit_cents=10_000))
    set_user_budget_ledger(InMemoryUserBudgetLedger())
    set_user_budget_policy(UserBudgetPolicy(InMemoryUserBudgetStore(), default_cents=0, ttl_s=0))
    yield
    set_rate_limiter(None)
    set_budget_ledger(None)
    set_user_budget_ledger(None)
    set_user_budget_policy(None)


@pytest.fixture
async def client(mem_store: InMemoryRunStore) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_store] = lambda: mem_store
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=auth_headers(),
    ) as http:
        yield http
    app.dependency_overrides.pop(get_store, None)
