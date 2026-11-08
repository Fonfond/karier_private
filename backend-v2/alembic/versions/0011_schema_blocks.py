"""Спринт 17: библиотека блоков схемы.

Revision ID: 0011_schema_blocks
Revises: 0010_schema_gost
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_schema_blocks"
down_revision: str | None = "0010_schema_gost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schema_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("block_type", sa.String(length=16), nullable=False, server_default="composite"),
        sa.Column("asset_type_id", sa.Uuid(), nullable=True),
        sa.Column("template_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["asset_type_id"], ["gis.asset_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_schema_blocks_code"),
        schema="gis",
        comment="Библиотека блоков однолинейной схемы (ПС, БКРУ, КТП)",
    )

    op.add_column("assets", sa.Column("schema_block_id", sa.Uuid(), nullable=True), schema="gis")
    op.add_column("assets", sa.Column("schema_local_x", sa.Numeric(10, 2), nullable=True), schema="gis")
    op.add_column("assets", sa.Column("schema_local_y", sa.Numeric(10, 2), nullable=True), schema="gis")
    op.add_column("assets", sa.Column("schema_role", sa.String(length=24), nullable=True), schema="gis")
    op.create_index("ix_assets_schema_block", "assets", ["schema_block_id"], schema="gis")


def downgrade() -> None:
    op.drop_index("ix_assets_schema_block", table_name="assets", schema="gis")
    op.drop_column("assets", "schema_role", schema="gis")
    op.drop_column("assets", "schema_local_y", schema="gis")
    op.drop_column("assets", "schema_local_x", schema="gis")
    op.drop_column("assets", "schema_block_id", schema="gis")
    op.drop_table("schema_blocks", schema="gis")
