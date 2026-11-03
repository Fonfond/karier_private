"""Pydantic-схемы: обходы, дефекты, фото."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InspectionKind = Literal["walk", "targeted", "emergency", "acceptance"]
InspectionStatus = Literal["draft", "in_progress", "submitted", "accepted", "rejected"]
ItemResult = Literal["ok", "defect", "critical", "not_found", "no_access"]
Severity = Literal["low", "medium", "high", "critical"]
DefectStatus = Literal["open", "in_progress", "fixed", "accepted", "rejected"]
GeoSource = Literal["exif", "device", "asset", "manual", "none"]


class AssetRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type_code: str
    type_icon: str | None = None


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID | None = None
    inspection_id: uuid.UUID | None = None
    defect_id: uuid.UUID | None = None
    kind: str
    purpose: str
    mime: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    captured_at: datetime | None = None
    received_at: datetime
    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    geo_source: str
    author_tab_no: str | None = None
    author_name: str | None = None
    watermark_applied: str | None = None
    content_url: str
    exif: dict = {}


class MediaListOut(BaseModel):
    items: list[MediaOut]
    total: int


class InspectionItemOut(BaseModel):
    id: uuid.UUID
    asset: AssetRef
    result: str | None = None
    comment: str | None = None
    checked_at: datetime | None = None
    media_count: int = 0


class InspectionOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    title: str | None = None
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    submitted_at: datetime | None = None
    note: str | None = None
    total: int = 0
    checked: int = 0
    defects: int = 0
    items: list[InspectionItemOut] = []


class InspectionListOut(BaseModel):
    items: list[InspectionOut]
    total: int


class InspectionCreate(BaseModel):
    kind: InspectionKind = "walk"
    title: str | None = Field(default=None, max_length=255)
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    note: str | None = None


class ItemResultIn(BaseModel):
    asset_id: uuid.UUID
    result: ItemResult
    comment: str | None = Field(default=None, max_length=1000)
    checked_at: datetime | None = None


class DefectOut(BaseModel):
    id: uuid.UUID
    asset: AssetRef
    inspection_id: uuid.UUID | None = None
    severity: str
    status: str
    category: str | None = None
    description: str
    detected_at: datetime
    detected_by_name: str | None = None
    fixed_at: datetime | None = None
    fixed_by_name: str | None = None
    photo_before: MediaOut | None = None
    photo_after: MediaOut | None = None
    photo_count: int = 0


class DefectListOut(BaseModel):
    items: list[DefectOut]
    total: int


class DefectCreate(BaseModel):
    asset_id: uuid.UUID
    severity: Severity = "medium"
    description: str = Field(min_length=3, max_length=2000)
    category: str | None = Field(default=None, max_length=32)
    inspection_id: uuid.UUID | None = None
    photo_before_id: uuid.UUID | None = None
    deadline_at: datetime | None = None


class DefectUpdate(BaseModel):
    severity: Severity | None = None
    status: DefectStatus | None = None
    description: str | None = Field(default=None, min_length=3, max_length=2000)
    photo_after_id: uuid.UUID | None = None
    note: str | None = None


class HistoryEntry(BaseModel):
    kind: str  # inspection | defect | media | switching
    at: datetime
    title: str
    detail: str | None = None
    status: str | None = None
    severity: str | None = None
    media_id: uuid.UUID | None = None
    author: str | None = None


class HistoryOut(BaseModel):
    asset_id: uuid.UUID
    items: list[HistoryEntry]
