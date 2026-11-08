"""请求身份：从 `Authorization: Bearer <token>` 解出用户。

身份只能来自服务端会话（R9）：路由与节点都**不允许**从请求体或模型输出里
读 user_id / role。这里解出的 `Identity` 也是工具治理的入参。

用 `HTTPBearer` 而不是手写 Header：OpenAPI 会声明 Bearer 安全方案，
Swagger 有 Authorize 按钮，生成的客户端也知道怎么带 token。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import ApiError
from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_token
from app.tools.registry import Identity

# auto_error=False：缺 token 时返回 None，由我们统一成 docs/03 约定的 401 JSON
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


def _unauthorized() -> ApiError:
    return ApiError(
        401,
        "UNAUTHORIZED",
        "缺少或无效的 token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Identity:
    """FastAPI 依赖。缺失/格式错/验签失败统一 401，不区分原因。"""
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials.strip()
    ):
        raise _unauthorized()

    try:
        claims = decode_token(credentials.credentials, secret=get_settings().session_secret)
    except InvalidTokenError:
        raise _unauthorized() from None

    return Identity(user_id=claims.user_id, roles=frozenset(claims.roles))
