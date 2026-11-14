"""会话管理请求/响应体（ADR-0040 / ADR-0043）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SessionId = Annotated[str, StringConstraints(min_length=1, max_length=64)]


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


class HiddenSessionRestoreRequest(BaseModel):
    """批量恢复已移除的会话（ADR-0049）；一次最多 50 个。"""

    model_config = ConfigDict(extra="forbid")

    session_ids: list[SessionId] = Field(min_length=1, max_length=50)


class HiddenSessionRestoreItem(BaseModel):
    """批量恢复的逐条结果（ADR-0055）；顺序与去重后的请求一致。"""

    session_id: str
    restored: bool


class HiddenSessionRestoreResponse(BaseModel):
    """批量恢复结果：保留计数，同时逐条说明哪些 id 真正恢复了（ADR-0055）。"""

    restored: int
    requested: int
    items: list[HiddenSessionRestoreItem]


class SessionRestoreAuditOut(BaseModel):
    """一次恢复操作的审计（ADR-0059）。"""

    id: str
    user_id: str
    session_ids: list[str]
    requested_count: int
    restored_count: int
    restored_at: datetime


class SessionRestoreAuditListResponse(BaseModel):
    items: list[SessionRestoreAuditOut]
