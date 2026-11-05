"""Спринт 10: мягкое удаление дефектов.

Revision ID: 0008_defect_delete
Revises: 0007_sprint9_ports
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_defect_delete"
down_revision: str | None = "0007_sprint9_ports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "defects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), schema="ops"
    )
    op.add_column("defects", sa.Column("deleted_by", sa.Uuid(), nullable=True), schema="ops")
    op.create_index(
        "ix_defects_active",
        "defects",
        ["pit_id", "deleted_at"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index("ix_defects_active", table_name="defects", schema="ops")
    op.drop_column("defects", "deleted_by", schema="ops")
    op.drop_column("defects", "deleted_at", schema="ops")
