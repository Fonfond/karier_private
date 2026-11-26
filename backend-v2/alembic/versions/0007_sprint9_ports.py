"""Спринт 9: позиции портов на однолинейной схеме.

Revision ID: 0007_sprint9_ports
Revises: 0006_sprint8_admin
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_sprint9_ports"
down_revision: str | None = "0006_sprint8_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # относительное положение порта на узле схемы: 0…1 по ширине и высоте
    op.add_column(
        "asset_ports", sa.Column("schema_x", sa.Numeric(6, 4), nullable=True), schema="gis"
    )
    op.add_column(
        "asset_ports", sa.Column("schema_y", sa.Numeric(6, 4), nullable=True), schema="gis"
    )


def downgrade() -> None:
    op.drop_column("asset_ports", "schema_y", schema="gis")
    op.drop_column("asset_ports", "schema_x", schema="gis")
