"""Спринт 16: ГОСТ-символы и рамка листа для однолинейной схемы.

Revision ID: 0010_schema_gost
Revises: 0009_break_glass
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_schema_gost"
down_revision: str | None = "0009_break_glass"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_types",
        sa.Column("schema_symbol", sa.String(length=24), nullable=False, server_default="load"),
        schema="gis",
    )
    op.add_column(
        "pits",
        sa.Column(
            "schema_frame",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="gis",
    )

    # начальные символы по кодам типов (дальше меняется в админке)
    op.execute(
        """
        UPDATE gis.asset_types SET schema_symbol = CASE
            WHEN code IN ('substation') THEN 'source'
            WHEN code IN ('bus_section') THEN 'busbar'
            WHEN code IN ('cell', 'yaku', 'yaku_1t', 'ktp', 'ksr', 'bkru') THEN 'breaker'
            WHEN code IN ('gen_diesel', 'gen_petrol', 'cuckoo') THEN 'generator'
            WHEN code IN ('pole') THEN 'line'
            WHEN code IN ('dmo', 'dmp', 'bmp', 'ekg', 'pump', 'mast') THEN 'load'
            ELSE 'load'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("pits", "schema_frame", schema="gis")
    op.drop_column("asset_types", "schema_symbol", schema="gis")
