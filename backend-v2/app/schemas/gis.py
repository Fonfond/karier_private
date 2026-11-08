"""Pydantic-схемы ГИС-реестра: типы, объекты, порты, подложки."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetStatus = Literal["on", "off", "standby", "maintenance", "decommissioned"]
AssetLifecycle = Literal["planned", "installed", "reserve", "written_off"]
PortKind = Literal["in", "out", "io"]


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
    location_text: str | None = None
    attrs: dict[str, Any] = {}
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    ports: list[PortOut] = []
    version: int
    updated_at: datetime


class AssetBriefOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type: TypeRefOut
    status: str
    is_mobile: bool
    grounded: bool
    x: float | None = None
    y: float | None = None
    location_text: str | None = None
    parent_id: uuid.UUID | None = None
    version: int
    updated_at: datetime


class AssetListOut(BaseModel):
    items: list[AssetBriefOut]
    total: int


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
    expected_version: int | None = Field(
        default=None, description="Оптимистическая блокировка: если версия не совпала — 409"
    )


class AssetTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str
    schema_symbol: str = "load"
    icon: str | None = None
    color: str | None = None
    port_template: dict[str, Any] = {}
    attr_schema: dict[str, Any] = {}
    required_attrs: list[str] = []
    is_mobile_default: bool = False
    sort_order: int = 100
    is_active: bool = True
    description: str | None = None
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    assets_count: int = 0


class AssetTypeCreate(BaseModel):
    code: str = Field(min_length=2, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=2, max_length=128)
    category: Literal["source", "line", "equipment", "mobile", "lighting", "aux", "pole"] = "equipment"
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    port_template: dict[str, Any] = {}
    attr_schema: dict[str, Any] = {}
    required_attrs: list[str] = []
    is_mobile_default: bool = False
    schema_symbol: str = Field(default="load", max_length=24)
    sort_order: int = 100
    description: str | None = None
    parent_id: uuid.UUID | None = None


class AssetTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    category: Literal["source", "line", "equipment", "mobile", "lighting", "aux", "pole"] | None = None
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    port_template: dict[str, Any] | None = None
    attr_schema: dict[str, Any] | None = None
    required_attrs: list[str] | None = None
    is_mobile_default: bool | None = None
    schema_symbol: str | None = Field(default=None, max_length=24)
    sort_order: int | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    clear_parent: bool = False
    is_active: bool | None = None


class SchemaLayoutItem(BaseModel):
    asset_id: uuid.UUID
    x: float
    y: float


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
    length_m: float | None = None
    cross_section_mm2: float | None = None
    cores: int | None = None
    line: LineOut | None = None
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
    type_code: str = Field(default="cell", max_length=48)
    params: dict[str, Any] = {}


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
