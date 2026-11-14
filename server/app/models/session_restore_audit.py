"""已移除会话的恢复审计（ADR-0059）。

批量恢复只返回「哪些 id 这次真正恢复了」，服务端没有留下「谁在何时恢复了
哪些会话」的凭据。这里按**一次恢复操作**落一行：`session_ids` 只记真正恢复
的 id（请求里不存在/属于别人/本来没移除的不写入），`requested_count` 记去重后
的请求数，便于区分「部分成功」与「全部失败」。

没有外键：会话仍由 `runs.session_id` 投影，审计行不随会话或 run 删除；保留期
独立配置（默认 365 天），由 `RetentionSweeper` 按 `restored_at` 清理。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class SessionRestoreAudit(Base):
    __tablename__ = "session_restore_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 真正恢复的 session_id，按请求顺序；不存在的 id 不写入
    session_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    #: 去重后的请求数；与 `session_ids` 的差值表示未恢复的 id 数
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    #: `len(session_ids)`，用 CHECK 保证冗余计数与数组一致
    restored_count: Mapped[int] = mapped_column(Integer, nullable=False)
    restored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "restored_count = jsonb_array_length(session_ids)",
            name="restored_count_matches_session_ids",
        ),
        # 管理页按用户查最近恢复；清理按时间删，两个方向各一条索引
        Index("idx_session_restore_audits_user_time", "user_id", text("restored_at DESC")),
        Index("idx_session_restore_audits_time", "restored_at"),
    )
