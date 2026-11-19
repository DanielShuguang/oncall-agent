"""CSV 导出下载审计（ADR-0094）。

审批/恢复审计/置顶审计的 CSV 导出是只读操作，但管理场景需要回答「谁在
什么时候、用什么过滤条件、导出了多少行」。这里只记录成功生成并即将返回的
导出：CSV 生成失败不写，审计写入失败则整个导出 503（fail closed），避免出现
无法留痕的下载。

`filters` 只保存标量过滤条件（用户/会话/日期/动作等），不保存行内容；由
`RetentionSweeper` 按 `ONCALL_EXPORT_AUDIT_RETENTION_DAYS`（默认 365 天）独立清理（ADR-0095）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

#: 目前会被审计的导出资源；新增导出点时同时扩展这里与 API 的校验。
EXPORT_RESOURCES: tuple[str, ...] = (
    "approvals",
    "approval_stats",
    "session_restores",
    "session_restore_stats",
    "session_pins",
    "session_pin_stats",
    "export_audits",
)


class ExportAudit(Base):
    __tablename__ = "export_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("row_count >= 0", name="ck_export_audits_row_count_non_negative"),
        CheckConstraint(
            "resource IN ("
            "'approvals', 'approval_stats', 'session_restores', "
            "'session_restore_stats', 'session_pins', 'session_pin_stats', 'export_audits'"
            ")",
            name="ck_export_audits_resource",
        ),
        Index("idx_export_audits_time", "created_at"),
        Index("idx_export_audits_user_time", "user_id", text("created_at DESC")),
        Index("idx_export_audits_resource_time", "resource", text("created_at DESC")),
    )
