"""工具覆盖策略的读取边界（W5 审阅补测）。"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.tools.policy import ToolOverride, ToolPolicy


class FailingStore:
    """模拟库不可用：读写都失败。"""

    def __init__(self) -> None:
        self.calls = 0

    async def load(self) -> dict[str, ToolOverride]:
        self.calls += 1
        raise SQLAlchemyError("database down")

    async def upsert(self, name: str, override: ToolOverride | None, *, updated_by: str) -> None:
        raise SQLAlchemyError("database down")

    async def replace(self, overrides: Mapping[str, ToolOverride], *, updated_by: str) -> None:
        raise SQLAlchemyError("database down")


async def test_strict_read_raises_instead_of_returning_empty_snapshot() -> None:
    store = FailingStore()
    policy = ToolPolicy(store, ttl_s=0)

    # 执行路径允许 stale：库挂了仍然按代码默认值继续，但要记日志
    assert await policy.overrides() == {}

    # 管理页不能把空快照当现状：否则读失败后的整表保存会删掉所有覆盖
    with pytest.raises(SQLAlchemyError):
        await policy.overrides(force=True, allow_stale=False)


async def test_cold_start_failure_backs_off_for_ttl() -> None:
    store = FailingStore()
    policy = ToolPolicy(store, ttl_s=10)

    assert await policy.overrides() == {}
    assert await policy.overrides() == {}
    # 冷启动失败后短时间内不要每个工具调用都打一次库
    assert store.calls == 1

    # 写入成功后的 invalidate 必须清掉失败退避，否则新配置会被 TTL 挡住
    policy.invalidate()
    assert await policy.overrides() == {}
    assert store.calls == 2

    # 管理页的严格读取不受退避影响，仍然要拿到真实错误
    with pytest.raises(SQLAlchemyError):
        await policy.overrides(force=True, allow_stale=False)
