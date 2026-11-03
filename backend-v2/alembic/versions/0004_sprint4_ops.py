"""Спринт 4: обходы, дефекты и фото с метаданными.

Создаёт `ops.inspections`, `ops.inspection_items`, `ops.defects`, `ops.media`.
Схемы предыдущих спринтов не изменяются.

Revision ID: 0004_sprint4_ops
Revises: 0003_sprint3_topology
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_sprint4_ops"
down_revision: str | None = "0003_sprint3_topology"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind in ('walk','targeted','emergency','acceptance')", name="ck_inspections_kind"),
        sa.CheckConstraint(
            "status in ('draft','in_progress','submitted','accepted','rejected')",
            name="ck_inspections_status",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
        comment="Обход: сессия проверки набора объектов",
    )
    op.create_index("ix_inspections_employee", "inspections", ["employee_id", "started_at"], schema="ops")

    op.create_table(
        "defects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("inspection_id", sa.Uuid(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("detected_by", sa.Uuid(), nullable=True),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fixed_by", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("photo_before_id", sa.Uuid(), nullable=True),
        sa.Column("photo_after_id", sa.Uuid(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("severity in ('low','medium','high','critical')", name="ck_defects_severity"),
        sa.CheckConstraint(
            "status in ('open','in_progress','fixed','accepted','rejected')", name="ck_defects_status"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["detected_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fixed_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inspection_id"], ["ops.inspections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
        comment="Дефект объекта: критичность, статус, фото до/после",
    )
    op.create_index("ix_defects_asset", "defects", ["asset_id", "detected_at"], schema="ops")
    op.create_index("ix_defects_status", "defects", ["status", "severity"], schema="ops")

    op.create_table(
        "inspection_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inspection_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "result is null or result in ('ok','defect','critical','not_found','no_access')",
            name="ck_inspection_items_result",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inspection_id"], ["ops.inspections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
        comment="Строка обхода: результат проверки объекта (пусто = ещё не проверен)",
    )
    op.create_index("ix_inspection_items_asset", "inspection_items", ["asset_id"], schema="ops")
    op.create_index("ix_inspection_items_inspection", "inspection_items", ["inspection_id"], schema="ops")

    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("inspection_id", sa.Uuid(), nullable=True),
        sa.Column("inspection_item_id", sa.Uuid(), nullable=True),
        sa.Column("defect_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lat", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("lon", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("accuracy_m", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("geo_source", sa.String(length=16), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("author_tab_no", sa.String(length=16), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("watermark_applied", sa.String(length=255), nullable=True),
        sa.Column("exif", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sync_state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("geo_source in ('exif','device','asset','manual','none')", name="ck_media_geo_source"),
        sa.CheckConstraint("kind in ('photo','video','document')", name="ck_media_kind"),
        sa.CheckConstraint("sync_state in ('pending','ready','failed')", name="ck_media_sync_state"),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["defect_id"], ["ops.defects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inspection_id"], ["ops.inspections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inspection_item_id"], ["ops.inspection_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
        comment="Фото с метаданными: время съёмки, координаты, автор, sha256, водяной знак",
    )
    op.create_index("ix_media_asset", "media", ["asset_id", "captured_at"], schema="ops")
    op.create_index("ix_media_defect", "media", ["defect_id"], schema="ops")
    op.create_index("ix_media_inspection", "media", ["inspection_id"], schema="ops")


def downgrade() -> None:
    op.drop_index("ix_media_inspection", table_name="media", schema="ops")
    op.drop_index("ix_media_defect", table_name="media", schema="ops")
    op.drop_index("ix_media_asset", table_name="media", schema="ops")
    op.drop_table("media", schema="ops")
    op.drop_index("ix_inspection_items_inspection", table_name="inspection_items", schema="ops")
    op.drop_index("ix_inspection_items_asset", table_name="inspection_items", schema="ops")
    op.drop_table("inspection_items", schema="ops")
    op.drop_index("ix_defects_status", table_name="defects", schema="ops")
    op.drop_index("ix_defects_asset", table_name="defects", schema="ops")
    op.drop_table("defects", schema="ops")
    op.drop_index("ix_inspections_employee", table_name="inspections", schema="ops")
    op.drop_table("inspections", schema="ops")
