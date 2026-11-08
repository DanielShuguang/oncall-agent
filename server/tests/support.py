"""测试共用工具。"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.security import create_token


def auth_headers(
    user_id: str = "u_102",
    roles: tuple[str, ...] = ("employee",),
    *,
    ttl_minutes: int = 60,
) -> dict[str, str]:
    """给 httpx 请求带一个合法 Bearer token。"""
    token = create_token(
        user_id=user_id,
        roles=roles,
        secret=get_settings().session_secret,
        ttl_minutes=ttl_minutes,
    )
    return {"Authorization": f"Bearer {token}"}
