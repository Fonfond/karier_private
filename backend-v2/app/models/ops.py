"""Ops-домен: обходы, дефекты, медиа."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base

SCHEMA = "ops"


class Inspection(Base):
    """Обход: сессия проверки набора объектов."""

    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(
            "kind in ('walk','targeted','emergency','acceptance')", name="ck_inspections_kind"
        ),
        CheckConstraint(
            "status in ('draft','in_progress','submitted','accepted','rejected')",
            name="ck_inspections_status",
        ),
        Index("ix_inspections_employee", "employee_id", "started_at"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey("gis.pits.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    kind = Column(String(16), nullable=False, default="walk")
    status = Column(String(16), nullable=False, default="in_progress")
    title = Column(String(255))
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    submitted_at = Column(DateTime(timezone=True))
    note = Column(Text)
    device_id = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship(
        "InspectionItem", back_populates="inspection", cascade="all, delete-orphan"
    )


class InspectionItem(Base):
    __tablename__ = "inspection_items"
    __table_args__ = (
        CheckConstraint(
            "result is null or result in ('ok','defect','critical','not_found','no_access')",
            name="ck_inspection_items_result",
        ),
        Index("ix_inspection_items_inspection", "inspection_id"),
        Index("ix_inspection_items_asset", "asset_id"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.inspections.id", ondelete="CASCADE"), nullable=False
    )
    asset_id = Column(Uuid, ForeignKey("gis.assets.id", ondelete="CASCADE"), nullable=False)
    result = Column(String(16))
    comment = Column(Text)
    checked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inspection = relationship("Inspection", back_populates="items")
    asset = relationship("Asset", lazy="joined")


class Defect(Base):
    __tablename__ = "defects"
    __table_args__ = (
        CheckConstraint(
            "severity in ('low','medium','high','critical')", name="ck_defects_severity"
        ),
        CheckConstraint(
            "status in ('open','in_progress','fixed','accepted','rejected')",
            name="ck_defects_status",
        ),
        Index("ix_defects_asset", "asset_id", "detected_at"),
        Index("ix_defects_status", "status", "severity"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey("gis.pits.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Uuid, ForeignKey("gis.assets.id", ondelete="CASCADE"), nullable=False)
    inspection_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.inspections.id", ondelete="SET NULL")
    )

    severity = Column(String(16), nullable=False, default="medium")
    status = Column(String(16), nullable=False, default="open")
    category = Column(String(32), default="other")
    description = Column(Text, nullable=False)

    detected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    detected_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    fixed_at = Column(DateTime(timezone=True))
    fixed_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    closed_at = Column(DateTime(timezone=True))

    photo_before_id = Column(Uuid)
    photo_after_id = Column(Uuid)
    deadline_at = Column(DateTime(timezone=True))
    note = Column(Text)

    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))

    asset = relationship("Asset", lazy="joined")


class Media(Base):
    """Фото/видео объекта с доказательными метаданными."""

    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("kind in ('photo','video','document')", name="ck_media_kind"),
        CheckConstraint(
            "geo_source in ('exif','device','asset','manual','none')", name="ck_media_geo_source"
        ),
        CheckConstraint(
            "sync_state in ('pending','ready','failed')", name="ck_media_sync_state"
        ),
        Index("ix_media_asset", "asset_id", "captured_at"),
        Index("ix_media_defect", "defect_id"),
        Index("ix_media_inspection", "inspection_id"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey("gis.pits.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Uuid, ForeignKey("gis.assets.id", ondelete="CASCADE"))
    inspection_id = Column(Uuid, ForeignKey(f"{SCHEMA}.inspections.id", ondelete="SET NULL"))
    inspection_item_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.inspection_items.id", ondelete="SET NULL")
    )
    defect_id = Column(Uuid, ForeignKey(f"{SCHEMA}.defects.id", ondelete="SET NULL"))

    kind = Column(String(16), nullable=False, default="photo")
    purpose = Column(String(24), nullable=False, default="inspection")
    storage_path = Column(String(500), nullable=False)
    mime = Column(String(128), nullable=False, default="image/jpeg")
    size_bytes = Column(BigInteger, nullable=False, default=0)
    width = Column(Integer)
    height = Column(Integer)
    sha256 = Column(String(64))

    captured_at = Column(DateTime(timezone=True))
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lat = Column(Numeric(10, 7))
    lon = Column(Numeric(10, 7))
    accuracy_m = Column(Numeric(8, 2))
    geo_source = Column(String(16), nullable=False, default="none")

    author_id = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    author_tab_no = Column(String(16))
    author_name = Column(String(255))
    watermark_applied = Column(String(255))
    exif = Column(JSONB, nullable=False, default=dict)
    sync_state = Column(String(16), nullable=False, default="ready")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))

    asset = relationship("Asset", lazy="joined")

class MaintenanceEntry(Base):
    """Запись журнала ТО: моточасы, топливо, ремонт."""

    __tablename__ = "maintenance_entries"
    __table_args__ = (
        CheckConstraint("kind in ('to','fuel','repair','other')", name="ck_maintenance_kind"),
        Index("ix_maintenance_asset", "asset_id"),
        {"schema": "ops"},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id = Column(Uuid, ForeignKey("gis.assets.id", ondelete="CASCADE"), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False)
    kind = Column(String(16), nullable=False, default="to")
    motor_hours = Column(Numeric(10, 1))
    fuel_liters = Column(Numeric(10, 1))
    fuel_level_pct = Column(Numeric(5, 1))
    cost = Column(Numeric(12, 2))
    note = Column(Text)
    author_id = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
