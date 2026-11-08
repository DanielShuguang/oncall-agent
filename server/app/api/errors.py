"""请求级错误响应。

docs/03 §2.4 约定：未鉴权、字段缺失这类「连流都建不起来」的错误返回
`4xx JSON {code, message}`，而不是 FastAPI 默认的 `{detail: ...}`。
运行期失败不在这里表达 —— 那是 200 + `run.failed` 事件。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """带机器可读 `code` 的请求级错误。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


async def api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # pragma: no cover - 注册时已限定类型
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
        headers=exc.headers,
    )
