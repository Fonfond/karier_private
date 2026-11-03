"""Pydantic-схемы: журнал аудита."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor_id: uuid.UUID | None = None
    actor_tab_no: str | None = None
    actor_role: str | None = None
    action: str
    entity: str | None = None
    entity_id: str | None = None
    result: str
    ip: str | None = None
    method: str | None = None
    path: str | None = None
    detail: str | None = None
    payload: Any = None


class AuditListOut(BaseModel):
    items: list[AuditOut]
    total: int
