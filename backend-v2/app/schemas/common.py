"""Pydantic-схемы: общие ответы."""

from __future__ import annotations

from pydantic import BaseModel


class MessageOut(BaseModel):
    message: str


class HealthOut(BaseModel):
    status: str
    service: str
    version: str
    database: str
