"""FastAPI 应用工厂。

启动：uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import ApiError, api_error_handler
from app.api.router import api_router
from app.approvals.service import ApprovalService
from app.approvals.store import get_approval_store
from app.core.config import get_settings
from app.core.db import configure as configure_db
from app.core.db import dispose as dispose_db
from app.core.logging import get_logger, setup_logging
from app.core.store import get_store
from app.gateway.meter import get_model_call_store
from app.runs.recovery import RunRecovery
from app.runs.retention import RetentionSweeper

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
    # 审批超时回收：即使没人打开审批列表，run 也要在 TTL 后收敛到 failed
    sweeper_stop = asyncio.Event()
    sweeper = asyncio.create_task(_sweep_expired_approvals(sweeper_stop))
    # 进程中断回收：崩溃后永远停在 running 的 run 也要收敛（ADR-0017）
    recovery = asyncio.create_task(_sweep_stale_runs(sweeper_stop))
    # 保留清理：过期事件与计量行按保留期删除（ADR-0021）
    retention = asyncio.create_task(_sweep_retention(sweeper_stop))
    yield
    sweeper_stop.set()
    for task in (sweeper, recovery, retention):
        task.cancel()
    for task in (sweeper, recovery, retention):
        with suppress(asyncio.CancelledError):
            await task
    if settings.store_backend == "postgres":
        await dispose_db()
    log.info("app_stopped")


APPROVAL_SWEEP_INTERVAL_S = 30.0


async def _sweep_expired_approvals(stop: asyncio.Event) -> None:
    service = ApprovalService(get_store(), get_approval_store())
    while not stop.is_set():
        try:
            expired = await service.expire_due()
            if expired:
                log.info("approvals_expired", count=len(expired))
        except Exception as exc:  # 库没起来时不能让后台任务炸掉整个进程
            log.warning("approval_sweep_failed", error=str(exc))
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=APPROVAL_SWEEP_INTERVAL_S)


async def _sweep_stale_runs(stop: asyncio.Event) -> None:
    settings = get_settings()
    recovery = RunRecovery(get_store(), settings=settings)
    while not stop.is_set():
        try:
            result = await recovery.reap()
            if result.reaped:
                log.warning(
                    "stale_runs_reaped",
                    count=len(result.reaped),
                    older_than=result.older_than.isoformat(),
                )
        except Exception as exc:  # 库没起来时不能让后台任务炸掉整个进程
            log.warning("stale_run_sweep_failed", error=str(exc))
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.recovery_interval_s)


async def _sweep_retention(stop: asyncio.Event) -> None:
    settings = get_settings()
    sweeper = RetentionSweeper(get_store(), get_model_call_store(), settings=settings)
    while not stop.is_set():
        try:
            result = await sweeper.sweep()
            if result.run_ids or result.calls or result.content_run_ids:
                log.info(
                    "retention_pruned",
                    runs=len(result.run_ids),
                    events=result.events,
                    calls=result.calls,
                    content_runs=len(result.content_run_ids),
                    batch=result.batch,
                    events_before=result.events_before.isoformat(),
                    calls_before=result.calls_before.isoformat(),
                    content_before=result.content_before.isoformat(),
                )
            if result.capped:
                # 跑到批次上限还有候选：清理在追赶，不是「已经清完」
                log.warning(
                    "retention_backlog_remaining",
                    batch=result.batch,
                    runs=len(result.run_ids),
                    events=result.events,
                    calls=result.calls,
                    content_runs=len(result.content_run_ids),
                )
        except Exception as exc:  # 库没起来时不能让后台任务炸掉整个进程
            log.warning("retention_sweep_failed", error=str(exc))
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.retention_interval_s)


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
