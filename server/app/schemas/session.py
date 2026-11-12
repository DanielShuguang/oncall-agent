"""会话管理请求体（ADR-0040）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SessionRenameRequest(BaseModel):
    """改会话显示标题；`null` 表示恢复默认（首条非空问题）。"""

    model_config = ConfigDict(extra="forbid")

    # 先放到 200，真正「裁掉首尾空白后 1–60」的检查在路由里做，错误信息更具体
    title: str | None = Field(default=None, max_length=200)
