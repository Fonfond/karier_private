"""Модели ГИС-реестра: карьер, подложки, типы объектов, объекты и порты."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin

SCHEMA = "gis"


class Pit(Base, TimestampMixin):
    """Карьер. В Спринте 2 один, но модель готова к нескольким."""

    __tablename__ = "pits"
    __table_args__ = (UniqueConstraint("code", name="uq_pits_code"), {"schema": SCHEMA})

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    code = Column(String(32), nullable=False)
    name = Column(String(128), nullable=False)
    timezone = Column(String(64), nullable=False, default="Asia/Irkutsk")
    crs_name = Column(String(64), nullable=False, default="Локальная СК карьера, м")
    is_active = Column(Boolean, nullable=False, default=True)


class MapLayer(Base, TimestampMixin):
    """Подложка карты: растровое изображение с привязкой к метрам."""

    __tablename__ = "map_layers"
    __table_args__ = (
        UniqueConstraint("pit_id", "name", name="uq_map_layers_pit_name"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey(f"{SCHEMA}.pits.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    kind = Column(String(16), nullable=False, default="raster")

    image_url = Column(String(500), nullable=False)
    width_px = Column(Integer, nullable=False)
    height_px = Column(Integer, nullable=False)
    # сколько метров в одном пикселе: задаёт масштаб подложки
    meters_per_pixel = Column(Numeric(10, 4), nullable=False, default=0.5)
    # начало координат подложки в метрах СК карьера
    origin_x = Column(Numeric(12, 2), nullable=False, default=0)
    origin_y = Column(Numeric(12, 2), nullable=False, default=0)
    rotation_deg = Column(Numeric(6, 2), nullable=False, default=0)

    min_zoom = Column(Integer, nullable=False, default=-3)
    max_zoom = Column(Integer, nullable=False, default=3)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    uploaded_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssetType(Base, TimestampMixin):
    """Справочник типов оборудования. Расширяется через админку без релиза."""

    __tablename__ = "asset_types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_asset_types_code"),
        CheckConstraint(
            "category in ('source','line','equipment','mobile','lighting','aux','pole')",
            name="ck_asset_types_category",
        ),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    code = Column(String(48), nullable=False)
    name = Column(String(128), nullable=False)
    category = Column(String(16), nullable=False, default="equipment")
    icon = Column(String(16), default="●")
    color = Column(String(16), default="#4C9AFF")

    # шаблон портов: {"ports":[{"code":"IN-1","name":"Ввод","kind":"in","voltage_kv":0.4}]}
    port_template = Column(JSONB, nullable=False, default=dict)
    # JSON-Schema дополнительных атрибутов (мощность, привод и т.п.)
    attr_schema = Column(JSONB, nullable=False, default=dict)
    required_attrs = Column(ARRAY(String), nullable=False, default=list)

    is_mobile_default = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text)

    # иерархия: категория → тип → подтип
    parent_id = Column(Uuid, ForeignKey(f"{SCHEMA}.asset_types.id", ondelete="SET NULL"))
    parent = relationship("AssetType", remote_side="AssetType.id", back_populates="children")
    children = relationship("AssetType", back_populates="parent", order_by="AssetType.sort_order")

    assets = relationship("Asset", back_populates="asset_type")


class Asset(Base, TimestampMixin):
    """Объект сети: подстанция, БКРУ, КТП, ДМО, ЭКГ, кукушка…

    Координаты x, y — в метрах локальной системы координат карьера.
    """

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("pit_id", "code", name="uq_assets_pit_code"),
        CheckConstraint(
            "status in ('on','off','standby','maintenance','decommissioned')",
            name="ck_assets_status",
        ),
        CheckConstraint(
            "lifecycle in ('planned','installed','reserve','written_off')",
            name="ck_assets_lifecycle",
        ),
        Index("ix_assets_pit_type", "pit_id", "asset_type_id"),
        Index("ix_assets_parent", "parent_asset_id"),
        Index("ix_assets_mobile", "is_mobile"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey(f"{SCHEMA}.pits.id", ondelete="CASCADE"), nullable=False)
    asset_type_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.asset_types.id", ondelete="RESTRICT"), nullable=False
    )
    parent_asset_id = Column(Uuid, ForeignKey(f"{SCHEMA}.assets.id", ondelete="SET NULL"))

    code = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    location_text = Column(String(255))

    status = Column(String(24), nullable=False, default="off")
    lifecycle = Column(String(24), nullable=False, default="installed")
    grounded = Column(Boolean, nullable=False, default=False)
    is_mobile = Column(Boolean, nullable=False, default=False)

    x = Column(Numeric(12, 2))
    y = Column(Numeric(12, 2))
    z = Column(Numeric(10, 2))
    lat = Column(Numeric(10, 7))
    lon = Column(Numeric(10, 7))

    # ручная раскладка в однолинейной схеме (пиксели холста)
    schema_x = Column(Numeric(10, 2))
    schema_y = Column(Numeric(10, 2))

    attrs = Column(JSONB, nullable=False, default=dict)

    created_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    updated_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, default=1)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))

    asset_type = relationship("AssetType", back_populates="assets", lazy="joined")
    ports = relationship(
        "AssetPort",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="AssetPort.sort_order",
    )
    parent = relationship("Asset", remote_side=[id], lazy="joined")


class AssetPort(Base):
    """Точка подключения объекта (ввод/отходящая/двунаправленный контакт)."""

    __tablename__ = "asset_ports"
    __table_args__ = (
        UniqueConstraint("asset_id", "code", name="uq_asset_ports_asset_code"),
        CheckConstraint("kind in ('in','out','io')", name="ck_asset_ports_kind"),
        Index("ix_asset_ports_asset", "asset_id"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id = Column(Uuid, ForeignKey(f"{SCHEMA}.assets.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(24), nullable=False)
    name = Column(String(64), nullable=False)
    kind = Column(String(8), nullable=False, default="in")
    nominal_voltage_kv = Column(Numeric(6, 3))
    phase = Column(String(8), default="3ph")
    sort_order = Column(Integer, nullable=False, default=0)

    # положение кружка порта на узле схемы: доли ширины/высоты узла (0…1)
    schema_x = Column(Numeric(6, 4))
    schema_y = Column(Numeric(6, 4))

    asset = relationship("Asset", back_populates="ports")
