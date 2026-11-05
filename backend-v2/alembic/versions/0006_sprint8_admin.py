"""Спринт 8: иерархия типов и ручная раскладка схемы.

Revision ID: 0006_sprint8_admin
Revises: 0005_sprint5_sync
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_sprint8_admin"
down_revision: str | None = "0005_sprint5_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # иерархия справочника: категория → тип → подтип
    op.add_column("asset_types", sa.Column("parent_id", sa.Uuid(), nullable=True), schema="gis")
    op.create_foreign_key(
        "fk_asset_types_parent",
        "asset_types",
        "asset_types",
        ["parent_id"],
        ["id"],
        source_schema="gis",
        referent_schema="gis",
        ondelete="SET NULL",
    )
    op.create_index("ix_asset_types_parent", "asset_types", ["parent_id"], schema="gis")

    # ручная раскладка узлов однолинейной схемы
    op.add_column("assets", sa.Column("schema_x", sa.Numeric(10, 2), nullable=True), schema="gis")
    op.add_column("assets", sa.Column("schema_y", sa.Numeric(10, 2), nullable=True), schema="gis")


def downgrade() -> None:
    op.drop_column("assets", "schema_y", schema="gis")
    op.drop_column("assets", "schema_x", schema="gis")
    op.drop_index("ix_asset_types_parent", table_name="asset_types", schema="gis")
    op.drop_constraint("fk_asset_types_parent", "asset_types", type_="foreignkey", schema="gis")
    op.drop_column("asset_types", "parent_id", schema="gis")
