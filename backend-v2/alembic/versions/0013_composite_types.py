"""Комплектные типы: шаблон состава (ячейки) для одного оборудования.

Revision ID: 0013_composite_types
Revises: 0012_maintenance_cables
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_composite_types"
down_revision: str | None = "0012_maintenance_cables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_types",
        sa.Column("is_composite", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="gis",
    )
    op.add_column(
        "asset_types",
        sa.Column("composite_template", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        schema="gis",
    )


def downgrade() -> None:
    op.drop_column("asset_types", "composite_template", schema="gis")
    op.drop_column("asset_types", "is_composite", schema="gis")
