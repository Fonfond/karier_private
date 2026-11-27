"""Pydantic-схемы ГИС-реестра: типы, объекты, порты, подложки."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetStatus = Literal["on", "off", "standby", "maintenance", "decommissioned"]
AssetLifecycle = Literal["planned", "installed", "reserve", "written_off"]
PortKind = Literal["in", "out", "io"]
EquipmentClass = Literal[
    "distribution",
    "transformer_assembly",
    "switching",
    "cell",
    "cable",
    "mobile",
    "line",
    "source",
    "equipment",
]
CellKind = Literal["in", "out", "sectional"]
CableLifecycleStatus = Literal["installed", "reserve", "repair"]
FieldDataType = Literal["number", "integer", "text", "boolean", "date", "select"]


class PortOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    nominal_voltage_kv: float | None = None
    sort_order: int


class TypeRefOut(BaseModel):
    code: str
    name: str
    category: str
    icon: str | None = None
    color: str | None = None
    # класс оборудования и вкладка реестра (этап 1 модели «Карьер»)
    equipment_class: str = "equipment"
    group_code: str | None = None


class FeederRefOut(BaseModel):
    """Отходящая линия (фидер), к которой относится объект.

    Объект принадлежит фидеру, если он достижим вниз по потоку от связей этой
    линии (см. docs/team/15-s8-feeders.md). Один объект может входить в несколько
    фидеров — например, секция с основным и резервным питанием.
    """

    id: uuid.UUID
    code: str
    name: str
    kind: str
    state: str


class AssetOut(BaseModel):
    id: uuid.UUID
    pit_id: uuid.UUID
    code: str
    name: str
    type: TypeRefOut
    status: str
    lifecycle: str
    grounded: bool
    is_mobile: bool
    x: float | None = None
    y: float | None = None
    z: float | None = None
    lat: float | None = None
    lon: float | None = None
    schema_x: float | None = None
    schema_y: float | None = None
    # ячейка внутри блока схемы: локальные координаты и размер блока (этап 3)
    schema_local_x: float | None = None
    schema_local_y: float | None = None
    schema_width: float | None = None
    schema_height: float | None = None
    location_text: str | None = None
    attrs: dict[str, Any] = {}
    # ячейка ПС/БКРУ и кабельный учёт (этап 1 модели, nullable)
    cell_kind: CellKind | None = None
    cell_no: int | None = None
    section_no: int | None = None
    lifecycle_status: CableLifecycleStatus | None = None
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    ports: list[PortOut] = []
    feeders: list[FeederRefOut] = []
    version: int
    updated_at: datetime


class AssetBriefOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type: TypeRefOut
    parent_id: uuid.UUID | None = None
    grouped: bool = False
    status: str
    is_mobile: bool
    grounded: bool
    x: float | None = None
    y: float | None = None
    location_text: str | None = None
    cell_kind: CellKind | None = None
    cell_no: int | None = None
    section_no: int | None = None
    lifecycle_status: CableLifecycleStatus | None = None
    feeders: list[FeederRefOut] = []
    version: int
    updated_at: datetime


class AssetListOut(BaseModel):
    items: list[AssetBriefOut]
    total: int
    feeder: FeederRefOut | None = None


class AssetCreate(BaseModel):
    """Новый объект. Координаты — в метрах СК карьера."""

    name: str = Field(min_length=2, max_length=255)
    type_code: str = Field(min_length=2, max_length=48)
    code: str | None = Field(default=None, max_length=64, description="Если не задан — сгенерируется")
    x: float | None = Field(default=None, description="Метры по X (восток)")
    y: float | None = Field(default=None, description="Метры по Y (север)")
    z: float | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    status: AssetStatus = "off"
    lifecycle: AssetLifecycle = "installed"
    location_text: str | None = Field(default=None, max_length=255)
    parent_id: uuid.UUID | None = None
    is_mobile: bool | None = Field(default=None, description="По умолчанию берётся из типа")
    attrs: dict[str, Any] = {}
    # ячейка ПС/БКРУ: ввод/отходящая/секционная и её номер
    cell_kind: CellKind | None = None
    cell_no: int | None = Field(default=None, ge=0, le=9999)
    section_no: int | None = Field(default=None, ge=0, le=99)
    # кабель: состояние изделия (по умолчанию для класса cable — installed)
    lifecycle_status: CableLifecycleStatus | None = None

    @field_validator("name", "type_code")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    x: float | None = None
    y: float | None = None
    z: float | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    status: AssetStatus | None = None
    lifecycle: AssetLifecycle | None = None
    location_text: str | None = Field(default=None, max_length=255)
    parent_id: uuid.UUID | None = None
    is_mobile: bool | None = None
    attrs: dict[str, Any] | None = None
    cell_kind: CellKind | None = None
    cell_no: int | None = Field(default=None, ge=0, le=9999)
    section_no: int | None = Field(default=None, ge=0, le=99)
    lifecycle_status: CableLifecycleStatus | None = None
    expected_version: int | None = Field(
        default=None, description="Оптимистическая блокировка: если версия не совпала — 409"
    )


class AssetTypeFieldOut(BaseModel):
    """Поле паспорта типа: из него фронтенд строит input динамической формы."""

    id: uuid.UUID
    code: str
    label: str
    unit: str | None = None
    data_type: str = "text"
    required: bool = False
    default_value: Any | None = None
    options: list[Any] = []
    min: float | None = None
    max: float | None = None
    group_label: str | None = None
    sort_order: int = 0


class AssetTypeFieldIn(BaseModel):
    """Описание поля при создании/правке типа (админ-конструктор)."""

    code: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=32)
    data_type: FieldDataType = "text"
    required: bool = False
    default_value: Any | None = None
    options: list[Any] = []
    min: float | None = None
    max: float | None = None
    group_label: str | None = Field(default=None, max_length=64)
    sort_order: int = 0


class AssetTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str
    equipment_class: str = "equipment"
    group_code: str | None = None
    has_maintenance: bool = False
    schema_symbol: str = "load"
    is_composite: bool = False
    composite_template: list[dict[str, Any]] = []
    icon: str | None = None
    color: str | None = None
    port_template: dict[str, Any] = {}
    attr_schema: dict[str, Any] = {}
    required_attrs: list[str] = []
    # заполняется только при GET /api/asset-types?with_fields=1 (или в админ-ответах)
    fields: list[AssetTypeFieldOut] = []
    is_mobile_default: bool = False
    sort_order: int = 100
    is_active: bool = True
    description: str | None = None
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    assets_count: int = 0


class AssetTypeCreate(BaseModel):
    code: str | None = Field(default=None, max_length=48)
    name: str = Field(min_length=2, max_length=128)
    category: Literal["source", "line", "equipment", "mobile", "lighting", "aux", "pole"] = "equipment"
    equipment_class: EquipmentClass | None = Field(
        default=None, description="Если не задан — выводится из category"
    )
    group_code: str | None = Field(default=None, max_length=32)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    port_template: dict[str, Any] = {}
    attr_schema: dict[str, Any] = {}
    required_attrs: list[str] = []
    # конструктор полей: если передан — attr_schema/required_attrs выводятся из него
    fields: list[AssetTypeFieldIn] = Field(default_factory=list)
    is_mobile_default: bool = False
    has_maintenance: bool = False
    # комплектность: тип содержит подтипы/ячейки (БКРУ, ПС) — Спринт 21+
    is_composite: bool = False
    composite_template: list[dict[str, Any]] = Field(default_factory=list)
    schema_symbol: str = Field(default="load", max_length=24)
    sort_order: int = 100
    description: str | None = None
    parent_id: uuid.UUID | None = None


class AssetTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    category: Literal["source", "line", "equipment", "mobile", "lighting", "aux", "pole"] | None = None
    equipment_class: EquipmentClass | None = None
    group_code: str | None = Field(default=None, max_length=32)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    port_template: dict[str, Any] | None = None
    attr_schema: dict[str, Any] | None = None
    required_attrs: list[str] | None = None
    fields: list[AssetTypeFieldIn] | None = None
    is_mobile_default: bool | None = None
    has_maintenance: bool | None = None
    is_composite: bool | None = None
    composite_template: list[dict[str, Any]] | None = None
    schema_symbol: str | None = Field(default=None, max_length=24)
    sort_order: int | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    clear_parent: bool = False
    is_active: bool | None = None


class SchemaLayoutItem(BaseModel):
    """Одна запись раскладки: узел на холсте, блок или ячейка внутри блока.

    Все поля координат/размера необязательны: автосейв присылает только то, что
    действительно изменилось (перетащили ячейку — придут ``local_x``/``local_y``,
    потянули за угол блока — ``width``/``height``). Старый клиент присылает
    ``x``/``y`` как раньше — это по-прежнему работает.
    """

    asset_id: uuid.UUID
    x: float | None = Field(default=None, description="Абсолютный X узла на холсте, px")
    y: float | None = Field(default=None, description="Абсолютный Y узла на холсте, px")
    width: float | None = Field(
        default=None, description="Ширина блока схемы, px (только для блока)"
    )
    height: float | None = Field(
        default=None, description="Высота блока схемы, px (только для блока)"
    )
    local_x: float | None = Field(
        default=None, description="X ячейки внутри своего блока, px (0…width блока)"
    )
    local_y: float | None = Field(
        default=None, description="Y ячейки внутри своего блока, px (0…height блока)"
    )


class SchemaPortItem(BaseModel):
    port_id: uuid.UUID
    x: float = Field(ge=0, le=1, description="Доля ширины узла, 0…1")
    y: float = Field(ge=0, le=1, description="Доля высоты узла, 0…1")


class SchemaLayoutIn(BaseModel):
    items: list[SchemaLayoutItem] = Field(default_factory=list, max_length=500)
    ports: list[SchemaPortItem] = Field(default_factory=list, max_length=1000)


class SchemaLayoutOut(BaseModel):
    updated: int
    updated_ports: int = 0
    updated_blocks: int = 0
    updated_cells: int = 0
    skipped: list[uuid.UUID] = []


class SchemaFrameIn(BaseModel):
    """Штамп и рамка листа: строки можно менять без релиза."""

    sheet_format: Literal["A4", "A3", "A1"] = "A3"
    organization: str = Field(default="ООО «Удоканская медь»", max_length=128)
    department: str = Field(default="Служба главного энергетика", max_length=128)
    object_name: str = Field(default="Однолинейная схема электроснабжения карьера", max_length=255)
    sheet: str = Field(default="Лист 1", max_length=32)
    scale: str = Field(default="б/м", max_length=16)
    developed_by: str = Field(default="", max_length=128)
    checked_by: str = Field(default="", max_length=128)
    approved_by: str = Field(default="", max_length=128)
    date: str = Field(default="", max_length=32)
    show_on_screen: bool = True


class SchemaFrameOut(SchemaFrameIn):
    pass


class MapLayerOut(BaseModel):
    id: uuid.UUID
    name: str
    image_url: str
    width_px: int
    height_px: int
    meters_per_pixel: float
    width_m: float
    height_m: float
    bounds: list[list[float]]
    min_zoom: int
    max_zoom: int
    version: int


class PowerPathNode(BaseModel):
    id: uuid.UUID | None = None
    code: str | None = None
    name: str
    type_code: str | None = None
    type_name: str | None = None
    type_icon: str | None = None
    role: str
    synthetic: bool = False
    link_id: uuid.UUID | None = None
    link_label: str | None = None
    link_state: str | None = None


class PowerPathOut(BaseModel):
    asset_id: uuid.UUID
    asset_name: str
    energized: bool = False
    source: PowerPathNode | None = None
    chain: list[PowerPathNode]
    reason: str | None = None
    note: str


# --- связи и линии ---------------------------------------------------------

class PortRefOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    voltage_kv: float | None = None
    schema_x: float | None = None
    schema_y: float | None = None


class AssetRefOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    type_icon: str | None = None
    status: str


class LineOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    voltage_kv: float | None = None
    conductor_mark: str | None = None
    length_m: float | None = None
    state: str
    links_count: int = 0


class LineCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=2, max_length=255)
    kind: Literal["overhead", "cable", "busbar"] = "cable"
    voltage_kv: float | None = None
    conductor_mark: str | None = None
    length_m: float | None = None


class LinkCreate(BaseModel):
    from_port_id: uuid.UUID
    to_port_id: uuid.UUID
    link_type: Literal["cable", "overhead", "busbar", "jumper", "internal"] = "cable"
    feed_role: Literal["main", "reserve", "backup"] = "main"
    state: Literal["connected", "open", "grounded"] = "connected"
    line_id: uuid.UUID | None = None
    cable_mark: str | None = Field(default=None, max_length=64)
    cable_no: str | None = Field(default=None, max_length=32)
    cable_status: Literal["in_work", "reserve", "repair", "dismounted"] = "in_work"
    installed_on: str | None = Field(default=None, max_length=255)
    route_note: str | None = None
    length_m: float | None = Field(default=None, ge=0)
    cross_section_mm2: float | None = Field(default=None, ge=0)
    cores: int | None = Field(default=None, ge=1, le=64)
    geometry: list[list[float]] = []
    attrs: dict[str, Any] = {}


class LinkUpdate(BaseModel):
    link_type: Literal["cable", "overhead", "busbar", "jumper", "internal"] | None = None
    feed_role: Literal["main", "reserve", "backup"] | None = None
    state: Literal["connected", "open", "grounded"] | None = None
    line_id: uuid.UUID | None = None
    cable_mark: str | None = Field(default=None, max_length=64)
    cable_no: str | None = Field(default=None, max_length=32)
    cable_status: Literal["in_work", "reserve", "repair", "dismounted"] | None = None
    installed_on: str | None = Field(default=None, max_length=255)
    route_note: str | None = None
    length_m: float | None = Field(default=None, ge=0)
    cross_section_mm2: float | None = Field(default=None, ge=0)
    cores: int | None = Field(default=None, ge=1, le=64)
    geometry: list[list[float]] | None = None
    expected_version: int | None = None


class LinkOut(BaseModel):
    id: uuid.UUID
    from_asset: AssetRefOut
    to_asset: AssetRefOut
    from_port: PortRefOut
    to_port: PortRefOut
    link_type: str
    feed_role: str
    state: str
    cable_mark: str | None = None
    cable_no: str | None = None
    cable_status: str = "in_work"
    installed_on: str | None = None
    route_note: str | None = None
    length_m: float | None = None
    cross_section_mm2: float | None = None
    cores: int | None = None
    line: LineOut | None = None
    # этап 2: кабель-объект реестра, установленный на участок (nullable)
    cable_asset_id: uuid.UUID | None = None
    cable_asset: AssetRefOut | None = None
    label: str
    version: int
    warnings: list[str] = []


class LinkListOut(BaseModel):
    items: list[LinkOut]
    total: int


# --- оперативные состояния -------------------------------------------------

class StateChangeIn(BaseModel):
    status: Literal["on", "off", "standby", "maintenance", "decommissioned"] | None = None
    grounded: bool | None = None
    reason: str | None = Field(default=None, max_length=255)


class StateChangeOut(BaseModel):
    asset: AssetOut
    energization_changed: bool
    affected_assets: int
    switching_op_id: uuid.UUID | None = None


# --- граф и проверки схемы -------------------------------------------------

class GraphNodeOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    type_name: str
    type_icon: str | None = None
    type_color: str | None = None
    category: str
    schema_symbol: str = "load"
    status: str
    grounded: bool
    energized: bool
    is_source: bool
    parent_id: uuid.UUID | None = None
    level: int = 0
    schema_x: float | None = None
    schema_y: float | None = None
    ports: list[PortRefOut] = []
    feeders: list[FeederRefOut] = []


class GraphEdgeOut(BaseModel):
    id: uuid.UUID
    from_asset_id: uuid.UUID
    to_asset_id: uuid.UUID
    label: str
    link_type: str
    state: str
    feed_role: str
    cable_mark: str | None = None
    length_m: float | None = None
    cross_section_mm2: float | None = None
    cores: int | None = None
    version: int = 1


class GraphBlockChildOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    role: str | None = None
    local_x: float | None = None
    local_y: float | None = None
    type_name: str | None = None
    params: dict[str, Any] = {}


class GraphJumperOut(BaseModel):
    id: uuid.UUID
    from_cell_id: uuid.UUID
    to_cell_id: uuid.UUID
    label: str | None = None


class GraphBlockOut(BaseModel):
    asset_id: uuid.UUID
    kind: str | None = Field(default=None, description="block_code: bkru_standard, contour…")
    width: float | None = Field(default=None, description="Ширина контура на схеме, px")
    height: float | None = Field(default=None, description="Высота контура на схеме, px")
    # этап 3: размер блока как отдельные поля БД (width/height оставлены для
    # обратной совместимости и содержат то же значение)
    schema_width: float | None = Field(
        default=None, description="gis.assets.schema_width: ширина блока, px"
    )
    schema_height: float | None = Field(
        default=None, description="gis.assets.schema_height: высота блока, px"
    )
    code: str
    name: str
    block_code: str | None = None
    schema_x: float | None = None
    schema_y: float | None = None
    collapsed: bool = False
    jumpers: list[GraphJumperOut] = []
    children: list[GraphBlockChildOut] = []


class TopologyGraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    blocks: list[GraphBlockOut] = []
    feeder: FeederRefOut | None = None


class TopologyIssueOut(BaseModel):
    level: str
    code: str
    message: str
    asset_id: uuid.UUID | None = None
    link_id: uuid.UUID | None = None


class ChildAssetOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    type_icon: str | None = None
    type_name: str
    status: str
    grounded: bool
    energized: bool
    ports: list[PortRefOut] = []

class SchemaBlockOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    block_type: str
    icon: str | None = None
    asset_type_code: str | None = None
    nodes_count: int = 0
    external_ports: int = 0
    roles: list[str] = []


class BlockInstantiateIn(BaseModel):
    x: float
    y: float
    name: str | None = Field(default=None, max_length=255)


class BlockInstantiateOut(BaseModel):
    asset_id: uuid.UUID
    code: str
    children: int
    block_code: str


class BlockCellIn(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    role: Literal["cell", "incoming", "outgoing"] = "cell"
    # "cell" — тип по умолчанию; если такого типа нет в справочнике, бэкенд
    # подберёт активный аналог (см. schema_blocks._resolve_type)
    type_code: str = Field(default="cell", max_length=48)
    params: dict[str, Any] = {}
    x: float | None = Field(default=None, description="Локальный X внутри блока")
    y: float | None = Field(default=None, description="Локальный Y внутри блока")


class BlockCellOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    role: str | None = None

class BlockCollapseIn(BaseModel):
    collapsed: bool


class BlockJumperIn(BaseModel):
    from_cell_id: uuid.UUID
    to_cell_id: uuid.UUID
    label: str | None = Field(default=None, max_length=64)


class LegendItemOut(BaseModel):
    symbol: str
    title: str
    count: int

class AssetGroupIn(BaseModel):
    parent_type_code: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=1, max_length=255)
    child_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    x: float | None = None
    y: float | None = None


class AssetGroupOut(BaseModel):
    parent_id: uuid.UUID
    children: int

class MaintenanceIn(BaseModel):
    at: datetime | None = None
    kind: Literal["to", "fuel", "repair", "other"] = "to"
    motor_hours: float | None = Field(default=None, ge=0)
    fuel_liters: float | None = Field(default=None, ge=0)
    fuel_level_pct: float | None = Field(default=None, ge=0, le=100)
    cost: float | None = Field(default=None, ge=0)
    note: str | None = None


class MaintenanceOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    at: datetime
    kind: str
    motor_hours: float | None = None
    fuel_liters: float | None = None
    fuel_level_pct: float | None = None
    cost: float | None = None
    note: str | None = None
    author_name: str | None = None

class PolesGenerateIn(BaseModel):
    type_code: str | None = None
    x1: float
    y1: float
    x2: float
    y2: float
    count: int = Field(ge=1, le=200)
    start: int = 1
    step: int = Field(default=1, ge=1, le=100)
    prefix: str = Field(default="оп.", max_length=16)
    source_asset_id: uuid.UUID | None = None
    target_asset_id: uuid.UUID | None = None
    link_type: Literal["overhead", "cable", "busbar", "jumper"] = "overhead"
    path: list[list[float]] | None = None


class PolesRenumberIn(BaseModel):
    type_code: str | None = None
    start: int = 1
    step: int = Field(default=1, ge=1, le=100)
    prefix: str = Field(default="оп.", max_length=16)


class PolesRenumberChainIn(BaseModel):
    anchor_asset_id: uuid.UUID | None = None
    link_id: uuid.UUID | None = None
    type_code: str | None = None
    start: int = 1
    step: int = Field(default=1, ge=1, le=100)
    prefix: str = Field(default="оп.", max_length=16)


class PolesResultOut(BaseModel):
    count: int
    first: str
    last: str
    ids: list[uuid.UUID] = []

class CompositePlaceIn(BaseModel):
    type_id: uuid.UUID
    x: float
    y: float
    name: str | None = None


class CompositeAttachIn(BaseModel):
    child_ids: list[uuid.UUID] = []


class CompositeOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    children: int = 0


# --- снимки схемы (Q-6: черновик / публикация) ------------------------------

SnapshotStatus = Literal["draft", "published"]


class SnapshotCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160, description="Название снимка")
    comment: str | None = Field(default=None, max_length=2000, description="Комментарий энергетика")


class SnapshotBriefOut(BaseModel):
    id: uuid.UUID
    title: str
    comment: str | None = None
    status: SnapshotStatus
    created_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    published_at: datetime | None = None
    published_by: uuid.UUID | None = None
    published_by_name: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class SnapshotOut(SnapshotBriefOut):
    payload: dict[str, Any]


class SnapshotListOut(BaseModel):
    items: list[SnapshotBriefOut]
    total: int
    published_id: uuid.UUID | None = None

class ContourIn(BaseModel):
    """Прямоугольный контур/блок, нарисованный на схеме."""

    name: str = Field(min_length=2, max_length=255)
    type_code: str = Field(min_length=2, max_length=48)
    x: float
    y: float
    width: float = Field(default=320, ge=80, le=4000)
    height: float = Field(default=220, ge=80, le=4000)
    comment: str | None = Field(default=None, max_length=255)


class ContourOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    x: float
    y: float
    width: float
    height: float


class PlaceAssetIn(BaseModel):
    """Поставить существующий объект реестра на схему (без дублирования)."""

    x: float
    y: float

class BulkCellsIn(BaseModel):
    """Пакетное добавление ячеек: сквозная нумерация и разбиение на секции."""

    count: int = Field(default=10, ge=1, le=200, description="Сколько ячеек создать")
    start: int = Field(default=1, ge=0, le=9999, description="Стартовый номер (сквозная нумерация)")
    prefix: str = Field(default="Яч. №", max_length=32)
    suffix: str = Field(default="", max_length=16)
    section_size: int = Field(default=0, ge=0, le=200, description="Ячеек в секции; 0 — без секций")
    section_prefix: str = Field(default="Секция", max_length=32)
    role: Literal["cell", "incoming", "outgoing"] = "outgoing"
    type_code: str | None = Field(default=None, max_length=48)


class BulkCellsOut(BaseModel):
    parent_id: uuid.UUID
    count: int
    sections: list[str] = []
    items: list[BlockCellOut] = []


class CellCableIn(BaseModel):
    """Отходящий кабель от ячейки до выбранного объекта (опора, разъединитель, КТП…)."""

    to_asset_id: uuid.UUID
    from_port_id: uuid.UUID | None = None
    to_port_id: uuid.UUID | None = None
    cable_mark: str | None = Field(default=None, max_length=64)
    length_m: float | None = Field(default=None, ge=0)
    cross_section_mm2: float | None = Field(default=None, ge=0)
    cores: int | None = Field(default=None, ge=1, le=64)
    link_type: Literal["cable", "overhead"] = "cable"


class LineEquipmentIn(BaseModel):
    """Оборудование линии (КТП, ЯКУ, разъединитель), присоединяемое к опоре/узлу."""

    anchor_asset_id: uuid.UUID
    type_code: str = Field(min_length=2, max_length=48)
    name: str | None = Field(default=None, max_length=255)
    cable_mark: str | None = Field(default=None, max_length=64)
    link_type: Literal["cable", "overhead"] = "cable"


class LineEquipmentOut(BaseModel):
    asset_id: uuid.UUID
    code: str
    name: str
    type_code: str
    link_id: uuid.UUID | None = None
    schema_x: float | None = None
    schema_y: float | None = None

class LineChainIn(BaseModel):
    """Линия между двумя ячейками через опоры: ВЛ или кабель."""

    from_asset_id: uuid.UUID
    to_asset_id: uuid.UUID
    poles: int = Field(default=5, ge=0, le=200, description="Сколько опор поставить между ячейками")
    prefix: str = Field(default="Опора", max_length=32)
    link_type: Literal["overhead", "cable"] = "overhead"
    cable_mark: str | None = Field(default=None, max_length=64)
    line_name: str | None = Field(default=None, max_length=255)
    line_code: str | None = Field(default=None, max_length=64)
    voltage_kv: float | None = Field(default=None, ge=0)


class LineChainPoleOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class LineChainOut(BaseModel):
    line_id: uuid.UUID
    line_code: str
    line_name: str
    poles: list[LineChainPoleOut] = []
    link_ids: list[uuid.UUID] = []