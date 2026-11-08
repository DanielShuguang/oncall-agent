"""对话相关请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatOptions(BaseModel):
    model: str | None = None
    max_steps: int = Field(default=12, ge=1, le=30)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    client_msg_id: str | None = Field(
        default=None,
        max_length=64,
        description="幂等键：重复提交返回同一个 run_id",
    )
    message: str = Field(min_length=1, max_length=4000)
    options: ChatOptions = Field(default_factory=ChatOptions)


class ApprovalResolveRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str | None = Field(default=None, max_length=500)
    scope: str = Field(default="once", pattern="^(once|session)$")
