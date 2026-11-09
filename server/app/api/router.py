"""路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import admin_kb, approvals, chat, cost, health, runs
from app.core.config import get_settings

api_router = APIRouter(prefix=get_settings().api_prefix)
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(runs.router)
api_router.include_router(approvals.router)
api_router.include_router(admin_kb.router)
api_router.include_router(cost.router)
