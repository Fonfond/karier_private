"""Журнал ТО и кабельный журнал.

Revision ID: 0012_maintenance_cables
Revises: 0011_schema_blocks
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_maintenance_cables"
down_revision: str | None = "0011_schema_blocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_types",
        sa.Column("has_maintenance", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="gis",
    )

    op.create_table(
        "maintenance_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="to"),
        sa.Column("motor_hours", sa.Numeric(10, 1), nullable=True),
        sa.Column("fuel_liters", sa.Numeric(10, 1), nullable=True),
        sa.Column("fuel_level_pct", sa.Numeric(5, 1), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind in ('to','fuel','repair','other')", name="ck_maintenance_kind"
        ),
        schema="ops",
    )
    op.create_index("ix_maintenance_asset", "maintenance_entries", ["asset_id"], schema="ops")
    op.create_index("ix_maintenance_at", "maintenance_entries", ["at"], schema="ops")

    op.add_column("links", sa.Column("cable_no", sa.String(length=32), nullable=True), schema="gis")
    op.add_column(
        "links",
        sa.Column("cable_status", sa.String(length=16), nullable=False, server_default="in_work"),
        schema="gis",
    )
    op.add_column("links", sa.Column("installed_on", sa.String(length=255), nullable=True), schema="gis")
    op.add_column("links", sa.Column("route_note", sa.Text(), nullable=True), schema="gis")
    op.create_check_constraint(
        "ck_links_cable_status",
        "links",
        "cable_status in ('in_work','reserve','repair','dismounted')",
        schema="gis",
    )


def downgrade() -> None:
    op.drop_constraint("ck_links_cable_status", "links", schema="gis")
    op.drop_column("links", "route_note", schema="gis")
    op.drop_column("links", "installed_on", schema="gis")
    op.drop_column("links", "cable_status", schema="gis")
    op.drop_column("links", "cable_no", schema="gis")
    op.drop_index("ix_maintenance_at", table_name="maintenance_entries", schema="ops")
    op.drop_index("ix_maintenance_asset", table_name="maintenance_entries", schema="ops")
    op.drop_table("maintenance_entries", schema="ops")
    op.drop_column("asset_types", "has_maintenance", schema="gis")
