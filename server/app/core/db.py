"""数据库引擎与会话工厂。

引擎是惰性创建的：导入本模块不会连接数据库，健康检查与请求各自决定
何时探活。`ONCALL_STORE_BACKEND=memory` 时不会走到这里。

连接池参数按「单实例 + 4 个 SSE 长连接」估算，W6 压测时再调。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure(database_url: str | None = None) -> None:
    """创建引擎。重复调用是幂等的，便于测试替换 DSN。"""
    global _engine, _sessionmaker
    if _engine is not None:
        return
    _engine = create_async_engine(
        database_url or get_settings().database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=5,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
