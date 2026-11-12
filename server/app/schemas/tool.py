"""工具注册、试调用与权限矩阵的请求/响应模型（docs/03 §5）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    is_write: bool
    timeout_ms: int
    #: 生效角色；空表示所有登录用户
    roles: list[str]
    enabled: bool
    #: 代码里的默认启用状态；为 false 时管理页不能把它打开
    code_enabled: bool
    #: 本环境是否存了覆盖（不是代码默认值）
    overridden: bool
    source: str = "builtin"


class ToolListResponse(BaseModel):
    items: list[ToolOut]


class ToolOverrideSnapshot(BaseModel):
    """覆盖快照；整个对象为 null 表示没有覆盖、走代码默认。"""

    enabled: bool | None = None
    #: null = 继承代码默认角色；[] = 所有登录用户
    roles: list[str] | None = None


class ToolChangeOut(BaseModel):
    id: int
    tool_name: str
    changed_by: str
    changed_at: datetime
    #: tool = 单工具开关；matrix = 权限矩阵整表保存
    source: str
    before: ToolOverrideSnapshot | None = None
    after: ToolOverrideSnapshot | None = None


class ToolHistoryResponse(BaseModel):
    items: list[ToolChangeOut]


class ToolUpdateRequest(BaseModel):
    """PATCH 只允许改启用开关；角色走权限矩阵，schema 属于代码契约。

    `enabled` 显式传 null 表示删除覆盖、回到代码默认值；省略字段表示不改。
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None


class ToolTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)


class ToolTestResponse(BaseModel):
    tool: str
    decision: str
    status: str
    result: Any = None
    error: str | None = None
    error_kind: str | None = None
    duration_ms: int
    attempts: int


class PermMatrixTool(BaseModel):
    name: str
    description: str
    is_write: bool
    enabled: bool
    code_enabled: bool
    #: 代码默认角色与默认启用状态，供「恢复默认」使用
    default_roles: list[str]
    default_enabled: bool
    roles: list[str]
    overridden: bool


class PermMatrixResponse(BaseModel):
    roles: list[str]
    tools: list[PermMatrixTool]


class PermMatrixToolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    enabled: bool
    #: 空数组 = 所有登录用户；只允许目录里的角色
    roles: list[str] = Field(default_factory=list, max_length=32)


class PermMatrixUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[PermMatrixToolUpdate] = Field(min_length=1, max_length=100)


class PermMatrixUpdateResponse(BaseModel):
    roles: list[str]
    tools: list[PermMatrixTool]
