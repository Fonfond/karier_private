"""Pydantic-схемы: сотрудники (администрирование)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

OtpChannel = Literal["telegram", "email", "manual"]
EmployeeStatus = Literal["active", "blocked", "dismissed"]


class EmployeeCreate(BaseModel):
    tab_no: str = Field(min_length=1, max_length=16, examples=["000003"])
    full_name: str = Field(min_length=3, max_length=255, examples=["Иванов Иван Иванович"])
    position: str | None = Field(default=None, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    phone_e164: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    telegram_id: int | None = None
    otp_channel: OtpChannel = "telegram"
    role: Literal["admin", "operator", "viewer", "contractor"] = "operator"
    access_until: datetime | None = None

    @field_validator("tab_no")
    @classmethod
    def normalize_tab(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "")


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=3, max_length=255)
    position: str | None = Field(default=None, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    phone_e164: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    telegram_id: int | None = None
    otp_channel: OtpChannel | None = None
    role: Literal["admin", "operator", "viewer", "contractor"] | None = None
    access_until: datetime | None = None


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tab_no: str
    full_name: str
    position: str | None = None
    department: str | None = None
    phone_e164: str | None = None
    email: str | None = None
    telegram_id: int | None = None
    otp_channel: str
    role: str
    status: str
    access_until: datetime | None = None
    has_credentials: bool = False
    mfa_enabled: bool = False
    last_login_at: datetime | None = None
    created_at: datetime


class EmployeeListOut(BaseModel):
    items: list[EmployeeOut]
    total: int


class InviteOut(BaseModel):
    delivery: str
    expires_in: int
    debug_code: str | None = None


class ResetPasswordOut(BaseModel):
    temp_password: str
    note: str = "Передайте пароль лично; пользователь сменит его при входе"
