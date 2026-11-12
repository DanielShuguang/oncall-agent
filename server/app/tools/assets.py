"""资产仓储：`query_cmdb` 查 `assets` 表，而不是进程内常量。

W1 的 `query_cmdb` 用 `FAKE_ASSETS` 硬编码两台设备；W2 的 seed 已经把 200 条
资产落进 `assets` 表（`tickets.asset_id` 也外键引用它），但工具一直没真正查表。
本模块补上这一步（ADR-0034）：

- 只返回 `owner_id = 当前用户` 的资产，身份由 ToolGuard 注入（R9）；
- 支持按 `asset_id` 精确查一台，仍然叠加 owner 过滤，不能越权；
- 内存实现用于测试与无库演示，Postgres 实现读 `assets` 表；
- 换成真实 CMDB 时替换这个仓储即可，工具治理与 Agent 节点不用动。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select

from app.models.business import Asset

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings


class AssetRepository(Protocol):
    async def list_for_owner(
        self, owner_id: str, *, asset_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """查某人名下资产，最多 `limit` 台；只读，不返回别人的资产。"""
        ...


#: 无库演示/测试用的最小资产集；字段与 `assets` 表一致。
DEMO_ASSETS: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "PC-20481",
        "owner_id": "u_102",
        "type": "laptop",
        "model": "ThinkPad T14",
        "location": "3F-东区",
        "ip": "10.20.31.44",
        "warranty_until": "2027-03-31",
        "status": "online",
    },
    {
        "asset_id": "PC-20499",
        "owner_id": "u_102",
        "type": "monitor",
        "model": "Dell U2723QE",
        "location": "3F-东区",
        "ip": None,
        "warranty_until": "2026-12-31",
        "status": "online",
    },
    {
        "asset_id": "PC-20517",
        "owner_id": "u_205",
        "type": "laptop",
        "model": "MacBook Pro 14",
        "location": "4F-研发",
        "ip": "10.20.32.8",
        "warranty_until": "2028-01-15",
        "status": "online",
    },
)


def _asset_dict(row: Asset) -> dict[str, Any]:
    return {
        "asset_id": row.id,
        "owner_id": row.owner_id,
        "type": row.type,
        "model": row.model,
        "location": row.location,
        "ip": row.ip,
        "warranty_until": row.warranty_to.isoformat() if row.warranty_to is not None else None,
        "status": row.status,
    }


class InMemoryAssetRepository:
    def __init__(self, assets: Iterable[dict[str, Any]] = DEMO_ASSETS) -> None:
        self._assets: dict[str, dict[str, Any]] = {
            str(asset["asset_id"]): dict(asset) for asset in assets
        }

    async def list_for_owner(
        self, owner_id: str, *, asset_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = [
            asset
            for asset in self._assets.values()
            if asset["owner_id"] == owner_id and (asset_id is None or asset["asset_id"] == asset_id)
        ]
        rows.sort(key=lambda asset: asset["asset_id"])
        return [dict(asset) for asset in rows[:limit]]

    def add(self, asset: dict[str, Any]) -> None:
        """测试/演示注入资产；生产数据来自 seed 或真实 CMDB。"""
        self._assets[str(asset["asset_id"])] = dict(asset)


class PostgresAssetRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_for_owner(
        self, owner_id: str, *, asset_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        query = select(Asset).where(Asset.owner_id == owner_id)
        if asset_id is not None:
            query = query.where(Asset.id == asset_id)
        query = query.order_by(Asset.id).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.scalars(query)).all()
        return [_asset_dict(row) for row in rows]


_repository: AssetRepository | None = None


def build_asset_repository(settings: Settings) -> AssetRepository:
    if settings.store_backend == "memory":
        return InMemoryAssetRepository()
    from app.core.db import get_sessionmaker

    return PostgresAssetRepository(get_sessionmaker())


def get_asset_repository() -> AssetRepository:
    global _repository
    if _repository is None:
        from app.core.config import get_settings

        _repository = build_asset_repository(get_settings())
    return _repository


def set_asset_repository(value: AssetRepository | None) -> None:
    global _repository
    _repository = value
