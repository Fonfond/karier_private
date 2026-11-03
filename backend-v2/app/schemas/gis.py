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
    icon: str | None = None
    color: str | None = None
    port_template: dict[str, Any] = {}
    attr_schema: dict[str, Any] = {}
    required_attrs: list[str] = []
    is_mobile_default: bool = False
    sort_order: int = 100
    is_active: bool = True
    description: str | None = None


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
    sort_order: int = 100
    description: str | None = None


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
    role: str
    synthetic: bool = False


class PowerPathOut(BaseModel):
    asset_id: uuid.UUID
    asset_name: str
    source: PowerPathNode | None = None
    chain: list[PowerPathNode]
    note: str
