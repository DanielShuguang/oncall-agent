"""资产仓储：只查本人、可按资产号缩小范围（ADR-0034）。"""

from __future__ import annotations

from app.tools.assets import InMemoryAssetRepository


async def test_list_for_owner_only_returns_own_assets() -> None:
    repo = InMemoryAssetRepository()

    rows = await repo.list_for_owner("u_102")
    assert [row["asset_id"] for row in rows] == ["PC-20481", "PC-20499"]
    assert all(row["owner_id"] == "u_102" for row in rows)

    other = await repo.list_for_owner("u_205")
    assert [row["asset_id"] for row in other] == ["PC-20517"]


async def test_list_for_owner_filters_asset_id_and_limits() -> None:
    repo = InMemoryAssetRepository()

    one = await repo.list_for_owner("u_102", asset_id="PC-20499")
    assert [row["asset_id"] for row in one] == ["PC-20499"]
    assert one[0]["warranty_until"] == "2026-12-31"
    assert one[0]["ip"] is None

    limited = await repo.list_for_owner("u_102", limit=1)
    assert [row["asset_id"] for row in limited] == ["PC-20481"]

    # 别人不能借 asset_id 越权查
    assert await repo.list_for_owner("u_205", asset_id="PC-20481") == []


async def test_add_injects_asset_for_tests_and_demo() -> None:
    repo = InMemoryAssetRepository()
    repo.add(
        {
            "asset_id": "PC-90001",
            "owner_id": "admin_1",
            "type": "laptop",
            "model": "ThinkPad X1",
            "location": "5F",
            "ip": "10.20.99.1",
            "warranty_until": "2028-01-01",
            "status": "online",
        }
    )

    rows = await repo.list_for_owner("admin_1")
    assert [row["asset_id"] for row in rows] == ["PC-90001"]
