"""Спринт 3: топология (линии, связи, переключения) и документы объекта.

Создаёт схему `ops` (документы) и таблицы `gis.lines`, `gis.links`,
`gis.switching_ops`. Схемы Спринтов 1–2 не изменяются.

Revision ID: 0003_sprint3_topology
Revises: 0002_sprint2_gis
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_sprint3_topology"
down_revision: str | None = "0002_sprint2_gis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        "lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("voltage_kv", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("source_asset_id", sa.Uuid(), nullable=True),
        sa.Column("conductor_mark", sa.String(length=64), nullable=True),
        sa.Column("length_m", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind in ('overhead','cable','busbar')", name="ck_lines_kind"),
        sa.CheckConstraint("state in ('energized','deenergized','grounded')", name="ck_lines_state"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["gis.assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pit_id", "code", name="uq_lines_pit_code"),
        schema="gis",
        comment="Логическая линия (фидер): объединяет участки links в «ф.21К»",
    )

    op.create_table(
        "switching_ops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_state", sa.String(length=32)),
        sa.Column("to_state", sa.String(length=32)),
        sa.Column("reason", sa.String(length=255)),
        sa.Column("performed_by", sa.Uuid(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="gis",
        comment="Журнал переключений: включение, отключение, заземление",
    )
    op.create_index("ix_switching_asset", "switching_ops", ["asset_id", "performed_at"], schema="gis")

    op.create_table(
        "links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("from_port_id", sa.Uuid(), nullable=False),
        sa.Column("to_port_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=True),
        sa.Column("link_type", sa.String(length=16), nullable=False),
        sa.Column("feed_role", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("geometry", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("length_m", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("cable_mark", sa.String(length=64), nullable=True),
        sa.Column("cross_section_mm2", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("cores", sa.Integer(), nullable=True),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("feed_role in ('main','reserve','backup')", name="ck_links_feed_role"),
        sa.CheckConstraint(
            "link_type in ('cable','overhead','busbar','jumper','internal')", name="ck_links_type"
        ),
        sa.CheckConstraint("state in ('connected','open','grounded')", name="ck_links_state"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_port_id"], ["gis.asset_ports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["line_id"], ["gis.lines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_port_id"], ["gis.asset_ports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="gis",
        comment="Участок связи порт→порт: кабель, ВЛ, шина, перемычка",
    )
    op.create_index("ix_links_from", "links", ["from_port_id"], schema="gis")
    op.create_index("ix_links_line", "links", ["line_id"], schema="gis")
    op.create_index("ix_links_to", "links", ["to_port_id"], schema="gis")
    op.create_index(
        "uq_links_pair_active",
        "links",
        ["from_port_id", "to_port_id"],
        unique=True,
        schema="gis",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("version", sa.String(length=32)),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "doc_type in ('schematic','settings','manual','other')", name="ck_documents_type"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deleted_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
        comment="Документы объекта: электросхемы, уставки, инструкции",
    )
    op.create_index("ix_documents_asset", "documents", ["asset_id", "created_at"], schema="ops")


def downgrade() -> None:
    op.drop_index("ix_documents_asset", table_name="documents", schema="ops")
    op.drop_table("documents", schema="ops")
    op.drop_index("ix_switching_asset", table_name="switching_ops", schema="gis")
    op.drop_table("switching_ops", schema="gis")
    op.drop_index("uq_links_pair_active", table_name="links", schema="gis")
    op.drop_index("ix_links_to", table_name="links", schema="gis")
    op.drop_index("ix_links_line", table_name="links", schema="gis")
    op.drop_index("ix_links_from", table_name="links", schema="gis")
    op.drop_table("links", schema="gis")
    op.drop_table("lines", schema="gis")
    op.execute("DROP SCHEMA IF EXISTS ops CASCADE")
