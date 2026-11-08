from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200_even_when_degraded() -> None:
    """中间件没起时也必须是 200 —— 前端要靠它渲染降级提示条。"""
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["checks"]) == {"db", "redis"}


def test_openapi_available() -> None:
    res = client.get("/openapi.json")
    assert res.status_code == 200
    assert "/api/chat/stream" in res.json()["paths"]
