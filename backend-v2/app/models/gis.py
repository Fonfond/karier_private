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
    # настройки рамки и штампа однолинейной схемы
    schema_frame = Column(JSONB, nullable=False, default=dict)


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


#: Классы оборудования (этап 1 модели «Карьер»): определяют вкладку реестра и
#: сценарий создания. ``equipment`` — «Прочее» для типов, которые ещё не разметил
#: администратор: новые типы не должны падать на CHECK.
EQUIPMENT_CLASSES = (
    "distribution",
    "transformer_assembly",
    "switching",
    "cell",
    "cable",
    "mobile",
    "line",
    "source",
    "equipment",
)


class AssetType(Base, TimestampMixin):
    """Справочник типов оборудования. Расширяется через админку без релиза."""

    __tablename__ = "asset_types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_asset_types_code"),
        CheckConstraint(
            "category in ('source','line','equipment','mobile','lighting','aux','pole')",
            name="ck_asset_types_category",
        ),
        CheckConstraint(
            "equipment_class in ("
            "'distribution','transformer_assembly','switching','cell','cable',"
            "'mobile','line','source','equipment')",
            name="ck_asset_types_equipment_class",
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

    # модель оборудования: класс (вкладка/сценарий) и группа для UI.
    # attr_schema/required_attrs остаются рабочими — двойная запись переходного
    # периода синхронизируется с gis.asset_type_fields (см. services/asset_fields.py)
    equipment_class = Column(
        String(32), nullable=False, default="equipment", server_default="equipment"
    )
    group_code = Column(String(32))

    is_mobile_default = Column(Boolean, nullable=False, default=False)
    # ведёт журнал ТО (моточасы, топливо)
    has_maintenance = Column(Boolean, nullable=False, default=False, server_default="false")
    # комплектное оборудование: при размещении создаёт дочерние ячейки по шаблону
    is_composite = Column(Boolean, nullable=False, default=False, server_default="false")
    composite_template = Column(JSONB, nullable=False, default=list, server_default="[]")
    # символ на однолинейной схеме: breaker, disconnector, busbar, load, generator, source, line, ct, arrester
    schema_symbol = Column(String(24), nullable=False, default="load")
    sort_order = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text)

    # иерархия: категория → тип → подтип
    parent_id = Column(Uuid, ForeignKey(f"{SCHEMA}.asset_types.id", ondelete="SET NULL"))
    parent = relationship("AssetType", remote_side="AssetType.id", back_populates="children")
    children = relationship("AssetType", back_populates="parent", order_by="AssetType.sort_order")

    assets = relationship("Asset", back_populates="asset_type")
    fields = relationship(
        "AssetTypeField",
        back_populates="asset_type",
        cascade="all, delete-orphan",
        order_by="AssetTypeField.sort_order, AssetTypeField.code",
    )


class AssetTypeField(Base):
    """Поле паспорта типа оборудования: из него строится форма создания объекта.

    Таблица — новый источник правды для динамической формы (этап 1). Старые
    ``asset_types.attr_schema``/``required_attrs`` сохраняются и синхронизируются
    (двойная запись), поэтому старые клиенты продолжают работать.
    """

    __tablename__ = "asset_type_fields"
    __table_args__ = (
        UniqueConstraint("asset_type_id", "code", name="uq_asset_type_fields_type_code"),
        CheckConstraint(
            "data_type in ('number','integer','text','boolean','date','select')",
            name="ck_asset_type_fields_data_type",
        ),
        Index("ix_asset_type_fields_type", "asset_type_id", "sort_order"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_type_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.asset_types.id", ondelete="CASCADE"), nullable=False
    )
    code = Column(String(48), nullable=False)
    label = Column(String(128), nullable=False)
    unit = Column(String(32))
    data_type = Column(String(16), nullable=False, default="text")
    required = Column(Boolean, nullable=False, default=False)
    default_value = Column(JSONB)
    options = Column(JSONB, nullable=False, default=list)
    # min/max — допустимый диапазон для number/integer
    min_value = Column("min", Numeric(14, 4))
    max_value = Column("max", Numeric(14, 4))
    group_label = Column(String(64))
    sort_order = Column(Integer, nullable=False, default=0)

    asset_type = relationship("AssetType", back_populates="fields")


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
        # ячейка: ввод / отходящая / секционная. Заполняется у дочерних объектов
        # ПС/БКРУ вместо свободного текста schema_role (этап 1 модели).
        CheckConstraint(
            "cell_kind in ('in','out','sectional')",
            name="ck_assets_cell_kind",
        ),
        # кабельный учёт: отдельная колонка вместо CHECK на JSONB attrs —
        # типизировано, индексируется и не зависит от набора ключей в attrs.
        # ``lifecycle`` (planned/installed/reserve/written_off) — жизненный цикл
        # объекта, ``lifecycle_status`` — состояние кабеля как изделия.
        CheckConstraint(
            "lifecycle_status in ('installed','reserve','repair')",
            name="ck_assets_lifecycle_status",
        ),
        # размер блока схемы: если задан — строго больше нуля (этап 3).
        # NULL — размер не задан (ячейка/символ), рисует клиент.
        CheckConstraint(
            "schema_width is null or schema_width > 0",
            name="ck_assets_schema_width_positive",
        ),
        CheckConstraint(
            "schema_height is null or schema_height > 0",
            name="ck_assets_schema_height_positive",
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
    # принадлежность блоку схемы: id родительского блока и локальные координаты
    schema_block_id = Column(Uuid, ForeignKey(f"{SCHEMA}.assets.id", ondelete="CASCADE"))
    schema_local_x = Column(Numeric(10, 2))
    schema_local_y = Column(Numeric(10, 2))
    # размер блока на схеме (px): ширина/высота прямоугольника ПС/БКРУ/КТП/контура.
    # Заполняется NodeResizer'ом через PUT /api/topology/layout (этап 3).
    schema_width = Column(Numeric(10, 2))
    schema_height = Column(Numeric(10, 2))
    schema_role = Column(String(24))

    attrs = Column(JSONB, nullable=False, default=dict)

    # ячейка ПС/БКРУ: вид, номер в секции, номер секции (этап 1 модели, nullable)
    cell_kind = Column(String(16))
    cell_no = Column(Integer)
    section_no = Column(Integer)
    # кабель: установлен / в запасе / в ремонте (только для класса cable)
    lifecycle_status = Column(String(16))

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
    parent = relationship(
        "Asset", remote_side=[id], lazy="joined", foreign_keys=[parent_asset_id]
    )


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

class SchemaBlock(Base):
    """Шаблон блока схемы: ПС, БКРУ, КТП и одиночные символы."""

    __tablename__ = "schema_blocks"
    __table_args__ = (
        UniqueConstraint("code", name="uq_schema_blocks_code"),
        CheckConstraint("block_type in ('composite','simple')", name="ck_schema_blocks_type"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    code = Column(String(48), nullable=False)
    name = Column(String(128), nullable=False)
    block_type = Column(String(16), nullable=False, default="composite")
    asset_type_id = Column(Uuid, ForeignKey(f"{SCHEMA}.asset_types.id", ondelete="SET NULL"))
    template_json = Column(JSONB, nullable=False, default=dict)
    icon = Column(String(16), default="▣")
    sort_order = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)

    asset_type = relationship("AssetType")


class SchemaSnapshot(Base, TimestampMixin):
    """Снимок однолинейной схемы: состояние топологии на дату.

    `payload` — полный слепок: узлы, порты, связи, блоки, раскладка и штамп.
    Опубликованный снимок неизменяем: публикация только фиксирует кто и когда,
    живая схема продолжает меняться отдельно.
    """

    __tablename__ = "schema_snapshots"
    __table_args__ = (
        CheckConstraint("status in ('draft','published')", name="ck_schema_snapshots_status"),
        Index("ix_schema_snapshots_pit_status", "pit_id", "status"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey(f"{SCHEMA}.pits.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(160), nullable=False)
    comment = Column(Text)
    status = Column(String(16), nullable=False, default="draft", server_default="draft")
    payload = Column(JSONB, nullable=False, default=dict)

    created_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    published_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    published_at = Column(DateTime(timezone=True))