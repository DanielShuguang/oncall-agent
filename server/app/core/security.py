"""本地签发的 JWT（HS256）。

v1 不接 SSO：运维用 `python -m app.cli token --user u_102 --roles employee`
给用户签一个短期 token，客户端以 `Authorization: Bearer <token>` 携带。
见 docs/03-api-contract.md 第 0 节与 ADR-0010。

为什么手写 HS256：这里只需要「签一个 / 验一个」，JWT 就是
`base64url(header).base64url(payload).base64url(HMAC-SHA256)`；
为了两个函数往私有化离线镜像里多塞一个依赖没有收益（R12）。

安全边界（改代码时不要放宽）：
- 只接受 `alg=HS256`，防止 `alg=none` 与算法混淆
- 签名比较用 `hmac.compare_digest`，防时序攻击
- `exp` 必须存在且过期即拒绝；`iat` 不接受未来时间
- 错误信息只用于日志，API 层统一回 401，不告诉客户端哪一步错了
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

ALGORITHM = "HS256"
DEFAULT_TTL_MINUTES = 480
#: 允许的时钟偏差；私有化部署里各机器 NTP 不一定完全同步
CLOCK_SKEW_S = 60


class InvalidTokenError(Exception):
    """token 不合法（结构 / 算法 / 签名 / 过期）。"""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: str
    roles: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:  # binascii.Error 是 ValueError 子类
        raise InvalidTokenError("base64 解码失败") from exc


def _sign(signing_input: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64encode(digest)


def create_token(
    *,
    user_id: str,
    roles: Iterable[str],
    secret: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    now: datetime | None = None,
) -> str:
    """签发 token。`roles` 去重排序，避免同一用户出现两份不同 claims。"""
    issued = now or datetime.now(UTC)
    payload = {
        "sub": user_id,
        "roles": sorted(set(roles)),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    header_segment = _b64encode(
        json.dumps({"alg": ALGORITHM, "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload_segment = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    )
    signing_input = f"{header_segment}.{payload_segment}".encode()
    return f"{header_segment}.{payload_segment}.{_sign(signing_input, secret)}"


def _decode_json(segment: str, label: str) -> dict[str, Any]:
    try:
        data = json.loads(_b64decode(segment))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidTokenError(f"{label} 不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise InvalidTokenError(f"{label} 必须是对象")
    return data


def decode_token(
    token: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> TokenClaims:
    """校验并解出 claims。任何不合法都抛 `InvalidTokenError`。"""
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError("token 结构不合法")
    header_segment, payload_segment, signature = parts

    header = _decode_json(header_segment, "header")
    if header.get("alg") != ALGORITHM:
        raise InvalidTokenError("不支持的签名算法")

    expected = _sign(f"{header_segment}.{payload_segment}".encode(), secret)
    if not hmac.compare_digest(expected, signature):
        raise InvalidTokenError("签名校验失败")

    payload = _decode_json(payload_segment, "payload")
    user_id = payload.get("sub")
    roles = payload.get("roles")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(user_id, str) or not user_id:
        raise InvalidTokenError("缺少 sub")
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise InvalidTokenError("roles 不合法")
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise InvalidTokenError("iat/exp 不合法")

    current = (now or datetime.now(UTC)).timestamp()
    if current >= expires_at:
        raise InvalidTokenError("token 已过期")
    if issued_at > current + CLOCK_SKEW_S:
        raise InvalidTokenError("iat 在未来")

    return TokenClaims(
        user_id=user_id,
        roles=tuple(sorted(set(roles))),
        issued_at=datetime.fromtimestamp(issued_at, UTC),
        expires_at=datetime.fromtimestamp(expires_at, UTC),
    )
