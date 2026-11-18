"""CSV 导出下载审计（ADR-0094）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.store import InMemoryRunStore
from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))
APPROVER = auth_headers(user_id="u_900", roles=("approver",))


async def test_export_audits_require_admin(client: AsyncClient) -> None:
    res = await client.get("/api/admin/export-audits")
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


async def test_records_pin_exports_and_lists(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    exported = await client.get("/api/admin/session-pins/export", headers=ADMIN)
    assert exported.status_code == 200
    await asyncio.sleep(0.002)
    stats = await client.get("/api/admin/session-pins/stats/export?days=7", headers=ADMIN)
    assert stats.status_code == 200

    res = await client.get("/api/admin/export-audits", headers=ADMIN)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    items = body["items"]
    assert [item["resource"] for item in items] == ["session_pin_stats", "session_pins"]
    assert all(item["user_id"] == "admin_1" for item in items)
    assert items[0]["filters"] == {"days": "7"}
    assert items[0]["row_count"] > 0
    assert items[1]["filters"] == {}
    assert items[1]["truncated"] is False

    filtered = await client.get("/api/admin/export-audits?resource=session_pins", headers=ADMIN)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["resource"] == "session_pins"


async def test_records_restore_and_approval_exports(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    for url in (
        "/api/admin/session-restores/export",
        "/api/admin/session-restores/stats/export?days=7",
    ):
        res = await client.get(url, headers=ADMIN)
        assert res.status_code == 200
    for url in (
        "/api/approvals/export",
        "/api/approvals/stats/export?days=7",
    ):
        res = await client.get(url, headers=APPROVER)
        assert res.status_code == 200

    res = await client.get("/api/admin/export-audits", headers=ADMIN)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 4
    assert {item["resource"] for item in body["items"]} == {
        "session_restores",
        "session_restore_stats",
        "approvals",
        "approval_stats",
    }


async def test_export_audit_cursor_and_filters(
    client: AsyncClient, mem_store: InMemoryRunStore
) -> None:
    for index in range(3):
        await mem_store.record_export_audit(
            user_id="u_102",
            resource="approvals",
            filters={"status": "pending"},
            row_count=index,
        )
        await asyncio.sleep(0.002)

    first = await client.get("/api/admin/export-audits?limit=1", headers=ADMIN)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["total"] == 3
    assert len(first_body["items"]) == 1
    cursor = first_body["next_cursor"]
    assert cursor

    second = await client.get(f"/api/admin/export-audits?limit=1&cursor={cursor}", headers=ADMIN)
    assert second.status_code == 200
    assert second.json()["total"] is None
    assert second.json()["items"][0]["row_count"] == 1

    mismatch = await client.get(
        f"/api/admin/export-audits?resource=session_pins&cursor={cursor}",
        headers=ADMIN,
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "INVALID_CURSOR"

    invalid = await client.get("/api/admin/export-audits?cursor=not-a-cursor", headers=ADMIN)
    assert invalid.status_code == 400

    single_end = await client.get("/api/admin/export-audits?created_from=2026-01-02", headers=ADMIN)
    assert single_end.status_code == 422

    reversed_range = await client.get(
        "/api/admin/export-audits?created_from=2026-01-03&created_to=2026-01-02",
        headers=ADMIN,
    )
    assert reversed_range.status_code == 422


async def test_export_audit_write_failure_fails_closed(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    monkeypatch.setattr(
        mem_store,
        "record_export_audit",
        AsyncMock(side_effect=SQLAlchemyError("boom")),
    )
    res = await client.get("/api/admin/session-pins/export", headers=ADMIN)
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"


async def test_export_audit_count_failure_returns_503(
    client: AsyncClient, mem_store: InMemoryRunStore, monkeypatch
) -> None:
    monkeypatch.setattr(
        mem_store,
        "count_export_audits",
        AsyncMock(side_effect=SQLAlchemyError("boom")),
    )
    res = await client.get("/api/admin/export-audits", headers=ADMIN)
    assert res.status_code == 503
    assert res.json()["code"] == "DATABASE_UNAVAILABLE"
