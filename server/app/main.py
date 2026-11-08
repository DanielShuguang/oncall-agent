"""FastAPI 应用工厂。

启动：uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import ApiError, api_error_handler
from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import configure as configure_db
from app.core.db import dispose as dispose_db
from app.core.logging import get_logger, setup_logging

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.env != "dev")
    if settings.store_backend == "postgres":
        # 只建连接池，不在这里连库：库没起来也要能返回 degraded 健康检查
        configure_db()
    log.info(
        "app_started",
        env=settings.env,
        mock_mode=settings.mock_mode,
        store_backend=settings.store_backend,
        api_prefix=settings.api_prefix,
    )
    yield
    if settings.store_backend == "postgres":
        await dispose_db()
    log.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OnCall API",
        version="0.1.0",
        description="私有化企业智能体工作台 —— 查资产 / 验权限 / 调工具 / 开单 / 审批 / 回填",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求级错误统一 {code, message}（docs/03 §2.4），未鉴权也走这里
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(api_router)
    return app


app = create_app()
