"""client_msg_id 幂等键按 user_id 作用域

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08

全局唯一的 client_msg_id 会在接入多用户后造成跨用户回放：用户 B 撞上
用户 A 的 key 时会拿到 A 的 run。改成 (user_id, client_msg_id) 联合唯一；
NULL 仍允许多行（空 key 视为未提供）。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_runs_client_msg_id", "runs", type_="unique")
    op.create_unique_constraint("uq_runs_user_client_msg", "runs", ["user_id", "client_msg_id"])


def downgrade() -> None:
    op.drop_constraint("uq_runs_user_client_msg", "runs", type_="unique")
    op.create_unique_constraint("uq_runs_client_msg_id", "runs", ["client_msg_id"])
