"""Pydantic-схемы документов."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["schematic", "settings", "manual", "other"]


class DocumentOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    doc_type: str
    doc_type_label: str
    title: str
    file_name: str
    mime: str
    size_bytes: int
    version: str | None = None
    created_at: datetime
    content_url: str
    sha256: str | None = None


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    doc_type: DocType | None = None
