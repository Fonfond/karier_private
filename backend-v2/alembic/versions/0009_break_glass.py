"""Аварийный доступ: признак break-glass у учётной записи.

Revision ID: 0009_break_glass
Revises: 0008_defect_delete
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_break_glass"
down_revision: str | None = "0008_defect_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("is_break_glass", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_column("employees", "is_break_glass", schema="auth")
