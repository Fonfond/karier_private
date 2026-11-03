"""Pydantic-схемы синхронизации, конфликтов и перемещений."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SyncEntity = Literal["asset", "move", "defect", "link"]
SyncOpKind = Literal["insert", "update", "delete"]
OpStatus = Literal["applied", "conflict_won", "conflict_lost", "duplicate", "rejected"]


class SyncOpIn(BaseModel):
    op_id: uuid.UUID
    entity: SyncEntity
    entity_id: uuid.UUID | None = None
    op: SyncOpKind = "update"
    patch: dict[str, Any] = {}
    base_version: int | None = None
    client_ts: datetime | None = None


class PushIn(BaseModel):
    device_id: str | None = Field(default=None, max_length=64)
    ops: list[SyncOpIn] = Field(default_factory=list, max_length=200)


class OpResultOut(BaseModel):
    op_id: uuid.UUID
    status: OpStatus
    version: int | None = None
    conflict_id: uuid.UUID | None = None
    message: str | None = None


class PushOut(BaseModel):
    results: list[OpResultOut]
    server_seq: int


class ChangeOut(BaseModel):
    seq: int
    entity: str
    entity_id: uuid.UUID
    op: str
    payload: dict[str, Any] = {}
    actor_id: uuid.UUID | None = None
    client_ts: datetime | None = None
    server_ts: datetime


class PullOut(BaseModel):
    changes: list[ChangeOut]
    last_seq: int
    has_more: bool


class ConflictOut(BaseModel):
    id: uuid.UUID
    entity: str
    entity_id: uuid.UUID
    kind: str
    winner: str
    winner_payload: dict[str, Any] = {}
    loser_payload: dict[str, Any] = {}
    client_ts: datetime | None = None
    server_ts: datetime | None = None
    note: str | None = None
    actor_name: str | None = None
    created_at: datetime


class ConflictListOut(BaseModel):
    items: list[ConflictOut]
    total: int


class MoveIn(BaseModel):
    x: float
    y: float
    note: str | None = Field(default=None, max_length=255)
    media_id: uuid.UUID | None = None
    client_ts: datetime | None = None
    source: Literal["online", "offline"] = "online"


class MoveOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    from_x: float | None = None
    from_y: float | None = None
    to_x: float
    to_y: float
    moved_at: datetime
    moved_by_name: str | None = None
    note: str | None = None
    source: str
    conflict: bool = False


class MoveListOut(BaseModel):
    items: list[MoveOut]
    total: int
