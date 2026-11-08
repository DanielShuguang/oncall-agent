"""测试夹具：默认用内存 store，不碰真库；Postgres 集成测试单独跳过。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.store import InMemoryRunStore, get_store
from app.main import app


@pytest.fixture
def mem_store() -> InMemoryRunStore:
    return InMemoryRunStore()


@pytest.fixture
async def client(mem_store: InMemoryRunStore) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_store] = lambda: mem_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_store, None)
