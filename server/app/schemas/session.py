"""会话管理请求/响应体（ADR-0040 / ADR-0043）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionRenameRequest(BaseModel):
    """改会话显示标题；`null` 表示恢复默认（首条非空问题）。"""

    model_config = ConfigDict(extra="forbid")

    # 先放到 200，真正「裁掉首尾空白后 1–60」的检查在路由里做，错误信息更具体
    title: str | None = Field(default=None, max_length=200)


class HiddenSessionOut(BaseModel):
    """从列表移除的会话（ADR-0043）。"""

    session_id: str
    title: str | None
    run_count: int
    hidden_at: datetime


class HiddenSessionListResponse(BaseModel):
    items: list[HiddenSessionOut]
    #: keyset 游标（ADR-0047）；只在当前页取满时返回，下一页为空时为 null
    next_cursor: str | None = None
