"""请求身份：从 `Authorization: Bearer <token>` 解出用户。

身份只能来自服务端会话（R9）：路由与节点都**不允许**从请求体或模型输出里
读 user_id / role。这里解出的 `Identity` 也是工具治理的入参。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from app.api.errors import ApiError
from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_token
from app.tools.registry import Identity

BEARER_PREFIX = "bearer "


def _unauthorized() -> ApiError:
    return ApiError(
        401,
        "UNAUTHORIZED",
        "缺少或无效的 token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_identity(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Identity:
    """FastAPI 依赖。缺失/格式错/验签失败统一 401，不区分原因。"""
    if not authorization:
        raise _unauthorized()

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != BEARER_PREFIX.strip() or not token.strip():
        raise _unauthorized()

    try:
        claims = decode_token(token.strip(), secret=get_settings().session_secret)
    except InvalidTokenError:
        raise _unauthorized() from None

    return Identity(user_id=claims.user_id, roles=frozenset(claims.roles))
