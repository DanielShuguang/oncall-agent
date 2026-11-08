"""健康检查：探 db 与 redis，任一不可用即 degraded。

不抛 500 —— 前端需要在降级状态下仍能渲染提示条。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)

PROBE_TIMEOUT_S = 0.8


async def _probe_db() -> bool:
    try:
        engine = get_engine()

        async def _query() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_query(), timeout=PROBE_TIMEOUT_S)
        return True
    except Exception as exc:
        log.debug("db_probe_failed", error=str(exc))
        return False


async def _probe_redis(url: str) -> bool:
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(url)
        try:
            await asyncio.wait_for(client.ping(), timeout=PROBE_TIMEOUT_S)
        finally:
            await client.aclose()
        return True
    except Exception as exc:
        log.debug("redis_probe_failed", error=str(exc))
        return False


@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    db_ok, redis_ok = await asyncio.gather(
        _probe_db(),
        _probe_redis(settings.redis_url),
    )
    healthy = db_ok and redis_ok
    return {
        "status": "ok" if healthy else "degraded",
        "env": settings.env,
        "mock_mode": settings.mock_mode,
        "checks": {"db": "up" if db_ok else "down", "redis": "up" if redis_ok else "down"},
    }
