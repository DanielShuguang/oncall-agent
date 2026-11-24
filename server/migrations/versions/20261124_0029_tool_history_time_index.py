"""index tool setting changes by changed_at for retention (ADR-0130).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_tool_setting_changes_time",
        "tool_setting_changes",
        ["changed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_tool_setting_changes_time", table_name="tool_setting_changes")
