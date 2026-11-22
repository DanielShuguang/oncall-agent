"""session restore audit records repinned count (ADR-0109).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_restore_audits",
        sa.Column(
            "repinned_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_session_restore_audits_repinned_count",
        "session_restore_audits",
        "repinned_count >= 0 AND repinned_count <= restored_count",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_session_restore_audits_repinned_count",
        "session_restore_audits",
        type_="check",
    )
    op.drop_column("session_restore_audits", "repinned_count")
