"""Спринт 2: ГИС-реестр — карьер, подложки, типы объектов, объекты, порты.

Создаёт схему `gis`. Схемы `auth`/`audit` из Спринта 1 не изменяются.

Revision ID: 0002_sprint2_gis
Revises: 0001_sprint1_auth
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_sprint2_gis"
down_revision: str | None = "0001_sprint1_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS gis")

    op.create_table(
        "pits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("crs_name", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_pits_code"),
        schema="gis",
        comment="Карьер (в Спринте 2 один, модель готова к нескольким)",
    )

    op.create_table(
        "asset_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("port_template", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attr_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_attrs", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("is_mobile_default", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category in ('source','line','equipment','mobile','lighting','aux','pole')",
            name="ck_asset_types_category",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_asset_types_code"),
        schema="gis",
        comment="Справочник типов оборудования: иконка, цвет, шаблон портов, схема атрибутов",
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_type_id", sa.Uuid(), nullable=False),
        sa.Column("parent_asset_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location_text", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("lifecycle", sa.String(length=24), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("is_mobile", sa.Boolean(), nullable=False),
        sa.Column("x", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("y", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("z", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("lat", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("lon", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "lifecycle in ('planned','installed','reserve','written_off')",
            name="ck_assets_lifecycle",
        ),
        sa.CheckConstraint(
            "status in ('on','off','standby','maintenance','decommissioned')",
            name="ck_assets_status",
        ),
        sa.ForeignKeyConstraint(["asset_type_id"], ["gis.asset_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_asset_id"], ["gis.assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pit_id", "code", name="uq_assets_pit_code"),
        schema="gis",
        comment="Объект сети. Координаты x/y — метры локальной СК карьера",
    )
    op.create_index("ix_assets_mobile", "assets", ["is_mobile"], schema="gis")
    op.create_index("ix_assets_parent", "assets", ["parent_asset_id"], schema="gis")
    op.create_index("ix_assets_pit_type", "assets", ["pit_id", "asset_type_id"], schema="gis")

    op.create_table(
        "map_layers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("meters_per_pixel", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("origin_x", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("origin_y", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("rotation_deg", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("min_zoom", sa.Integer(), nullable=False),
        sa.Column("max_zoom", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pit_id", "name", name="uq_map_layers_pit_name"),
        schema="gis",
        comment="Растровая подложка карты с привязкой к метрам (масштаб, смещение, поворот)",
    )

    op.create_table(
        "asset_ports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("nominal_voltage_kv", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("phase", sa.String(length=8), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind in ('in','out','io')", name="ck_asset_ports_kind"),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "code", name="uq_asset_ports_asset_code"),
        schema="gis",
        comment="Порт (точка подключения): ввод, отходящая, двунаправленный контакт",
    )
    op.create_index("ix_asset_ports_asset", "asset_ports", ["asset_id"], schema="gis")


def downgrade() -> None:
    op.drop_index("ix_asset_ports_asset", table_name="asset_ports", schema="gis")
    op.drop_table("asset_ports", schema="gis")
    op.drop_table("map_layers", schema="gis")
    op.drop_index("ix_assets_pit_type", table_name="assets", schema="gis")
    op.drop_index("ix_assets_parent", table_name="assets", schema="gis")
    op.drop_index("ix_assets_mobile", table_name="assets", schema="gis")
    op.drop_table("assets", schema="gis")
    op.drop_table("asset_types", schema="gis")
    op.drop_table("pits", schema="gis")
    op.execute("DROP SCHEMA IF EXISTS gis CASCADE")
