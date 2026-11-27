"""Схемы этапа 2: составные устройства, переключение, кабельный учёт."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

CellKindLiteral = Literal["in", "out", "sectional"]
CableStatusLiteral = Literal["installed", "reserve", "repair"]


# --- составные устройства (БКРУ / ПС / КТП) ---------------------------------


class CompositeCreateIn(BaseModel):
    """Создать блок с составом по шаблону типа одной транзакцией."""

    type_code: str = Field(min_length=2, max_length=48, description="Код типа (bkru, substation, ktp…)")
    name: str = Field(min_length=2, max_length=255, description="Название блока")
    x: float = Field(description="Пиксели по X на холсте схемы")
    y: float = Field(description="Пиксели по Y на холсте схемы")
    code: str | None = Field(default=None, max_length=64, description="Код блока; иначе сгенерируется")
    cells_per_section: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Ячеек в секции для ПС 35/6 (по умолчанию 17; допустимо 1…50)",
    )


class CompositeCellOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    cell_kind: CellKindLiteral
    cell_no: int
    section_no: int
    status: str
    grounded: bool = False
    voltage_kv: float | None = None
    local_x: float | None = None
    local_y: float | None = None


class CompositeSectionOut(BaseModel):
    section_no: int
    label: str
    voltage_kv: float | None = None
    cells: list[CompositeCellOut] = []


class DisconnectorOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    cell_kind: CellKindLiteral
    status: str
    grounded: bool = False


class CompositeBlockOut(BaseModel):
    """Блок составного устройства (дубль верхнеуровневых полей для удобства UI)."""

    id: uuid.UUID
    code: str
    name: str
    type_code: str
    schema_x: float | None = None
    schema_y: float | None = None


class CompositeCreateOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    schema_x: float | None = None
    schema_y: float | None = None
    template_version: int = 1
    children: int = 0
    block: CompositeBlockOut | None = None
    sections: list[CompositeSectionOut] = []
    cells: list[CompositeCellOut] = []
    disconnector: DisconnectorOut | None = None
    disconnector_id: uuid.UUID | None = None


# --- переключение ячейки / разъединителя -------------------------------------


class ToggleIn(BaseModel):
    """Без ``state`` — переключить (on→off, иначе on); со ``state`` — выставить."""

    state: Literal["on", "off"] | None = None
    reason: str | None = Field(default=None, max_length=255)


class ToggleOut(BaseModel):
    asset_id: uuid.UUID
    code: str
    name: str
    cell_kind: CellKindLiteral | None = None
    status: Literal["on", "off"] = "off"
    previous_status: str
    changed: bool = False
    grounded: bool = False
    #: оперативное «под напряжением»: включено и не заземлено (для цвета на схеме)
    energized: bool = False
    #: фактическое напряжение на объекте: номинал при включении, иначе 0
    voltage_kv: float = 0.0
    nominal_voltage_kv: float | None = None
    #: достижимость от источника по графу связей (может быть False без связей)
    topology_energized: bool = False


# --- кабельный учёт ---------------------------------------------------------


class CableAssetRefOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    type_icon: str | None = None
    status: str


class CableOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    status: str
    lifecycle_status: CableStatusLiteral = "installed"
    cable_mark: str | None = None
    section_mm2: float | None = None
    length_m: float | None = None
    voltage_kv: float | None = None
    link_id: uuid.UUID | None = None
    link_label: str | None = None
    link_state: str | None = None
    installed_on: str | None = None
    from_asset: CableAssetRefOut | None = None
    to_asset: CableAssetRefOut | None = None
    attrs: dict[str, Any] = {}
    version: int = 1
    updated_at: datetime
    warnings: list[str] = []


class CableInstallIn(BaseModel):
    """Куда ставим кабель: участок линии (link_id) или объект (asset_id)."""

    link_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    cable_mark: str | None = Field(default=None, max_length=64)
    length_m: float | None = Field(default=None, ge=0)
    cross_section_mm2: float | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _target_required(self) -> "CableInstallIn":
        if self.link_id is None and self.asset_id is None:
            raise ValueError("Укажите link_id или asset_id")
        return self


class CableReturnIn(BaseModel):
    """Снятие кабеля: в запас (reserve) или в ремонт (repair/installed)."""

    status: CableStatusLiteral = "reserve"
    link_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)


class CableInstallOut(BaseModel):
    cable: CableOut
    link_id: uuid.UUID | None = None
    link_label: str | None = None


class CableReturnOut(BaseModel):
    cable: CableOut
    detached_links: list[uuid.UUID] = []
