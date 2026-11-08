"""JWT 鉴权（W1 D2）：签发/验签、401 语义、run 归属隔离。"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.security import (
    ALGORITHM,
    InvalidTokenError,
    create_token,
    decode_token,
)
from app.main import app
from tests.support import auth_headers

SECRET = get_settings().session_secret
USER = "u_102"


def _b64(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _client(headers: dict[str, str]) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    )


def test_roundtrip_claims() -> None:
    token = create_token(user_id=USER, roles=["employee", "employee", "it_support"], secret=SECRET)
    claims = decode_token(token, secret=SECRET)
    assert claims.user_id == USER
    assert claims.roles == ("employee", "it_support")
    assert claims.expires_at > claims.issued_at


def test_wrong_secret_is_rejected() -> None:
    token = create_token(user_id=USER, roles=["employee"], secret=SECRET)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret="another-secret")


def test_tampered_payload_is_rejected() -> None:
    token = create_token(user_id=USER, roles=["employee"], secret=SECRET)
    header, _, signature = token.split(".")
    tampered = _b64({"sub": "u_999", "roles": ["approver"], "iat": 0, "exp": 2**31 - 1})
    with pytest.raises(InvalidTokenError):
        decode_token(f"{header}.{tampered}.{signature}", secret=SECRET)


def test_alg_none_is_rejected() -> None:
    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64({"sub": USER, "roles": [], "iat": 0, "exp": 2**31 - 1})
    with pytest.raises(InvalidTokenError):
        decode_token(f"{header}.{payload}.", secret=SECRET)


def test_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token = create_token(user_id=USER, roles=["employee"], secret=SECRET, ttl_minutes=1, now=past)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret=SECRET)


def test_future_iat_is_rejected() -> None:
    future = datetime.now(UTC) + timedelta(minutes=10)
    token = create_token(user_id=USER, roles=["employee"], secret=SECRET, now=future)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret=SECRET)


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c.d", "a.b", "!!!.!!!.!!!"])
def test_malformed_tokens_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_token(bad, secret=SECRET)


async def test_missing_token_returns_401_json() -> None:
    async with _client({}) as http:
        res = await http.get("/api/runs")
    assert res.status_code == 401
    assert res.json() == {"code": "UNAUTHORIZED", "message": "缺少或无效的 token"}
    assert res.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    ["Bearer not-a-token", "Token abc", "Bearer", "Basic dXNlcjpwYXNz"],
)
async def test_bad_authorization_header_returns_401(authorization: str) -> None:
    async with _client({"Authorization": authorization}) as http:
        res = await http.get("/api/runs")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


async def test_health_is_public() -> None:
    async with _client({}) as http:
        res = await http.get("/api/health")
    assert res.status_code == 200


def test_openapi_declares_bearer_scheme() -> None:
    """Swagger / 生成客户端要能看到 Bearer 鉴权，而不是靠猜 header。"""
    schema = app.openapi()
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    assert {"BearerAuth": []} in schema["paths"]["/api/runs"]["get"]["security"]


async def test_token_identity_drives_run_ownership(client: AsyncClient) -> None:
    async with _client(auth_headers("u_205")) as other:
        async with other.stream(
            "POST", "/api/chat/stream", json={"session_id": "s", "message": "打印机离线"}
        ) as res:
            assert res.status_code == 200
            lines = [line async for line in res.aiter_lines()]

        events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
        run_id = events[0]["run_id"]
        detail = (await other.get(f"/api/runs/{run_id}")).json()
        assert detail["user_id"] == "u_205"

    # 默认 client 是 u_102：别人的 run 一律 404（不泄露存在性）
    assert (await client.get(f"/api/runs/{run_id}")).status_code == 404
    assert (await client.get(f"/api/runs/{run_id}/events")).status_code == 404


async def test_signed_but_unsigned_algorithm_still_rejected() -> None:
    """alg 必须是 HS256，不能靠 header 自述。"""
    header = _b64({"alg": "HS512", "typ": "JWT"})
    payload = _b64({"sub": USER, "roles": [], "iat": 0, "exp": 2**31 - 1})
    with pytest.raises(InvalidTokenError):
        decode_token(f"{header}.{payload}.x", secret=SECRET)
    assert ALGORITHM == "HS256"
