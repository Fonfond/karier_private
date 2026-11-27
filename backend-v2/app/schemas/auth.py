"""Pydantic-схемы: авторизация, профиль, 2FA."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- вход ------------------------------------------------------------------

class LoginRequest(BaseModel):
    tab_no: str = Field(min_length=1, max_length=16, description="Табельный номер")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("tab_no")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "")


class MfaVerifyRequest(BaseModel):
    challenge_token: str
    code: str = Field(min_length=4, max_length=16)


class RegisterStartRequest(BaseModel):
    tab_no: str = Field(min_length=1, max_length=16)

    @field_validator("tab_no")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "")


class RegisterStartOut(BaseModel):
    delivery: str = Field(description="Канал доставки кода: telegram | email | manual")
    delivery_target: str | None = Field(default=None, description="Куда отправлен код (маскировано)")
    expires_in: int = Field(description="Сколько секунд остаётся жить выданному коду (0 — кода нет)")
    next_step: str = Field(
        default="code_sent",
        description="code_sent | code_required | already_registered",
    )


class RegisterVerifyRequest(BaseModel):
    tab_no: str = Field(min_length=1, max_length=16)
    code: str = Field(min_length=4, max_length=8)

    @field_validator("tab_no")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "")


class RegisterVerifyOut(BaseModel):
    setup_token: str
    expires_in: int


class RegisterCompleteRequest(BaseModel):
    setup_token: str
    password: str = Field(min_length=10, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


# --- выход -----------------------------------------------------------------

class UserOut(ORMModel):
    id: uuid.UUID
    tab_no: str
    full_name: str
    position: str | None = None
    department: str | None = None
    role: str
    permissions: list[str] = []
    status: str
    mfa_enabled: bool = False
    must_change_password: bool = False
    last_login_at: datetime | None = None


class TokenPairOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    mfa_required: bool = False


class MfaRequiredOut(BaseModel):
    mfa_required: bool = True
    challenge_token: str
    expires_in: int
    full_name: str


class SessionOut(ORMModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    current: bool = False


# --- 2FA -------------------------------------------------------------------

class TotpEnrollOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class RecoveryCodesOut(BaseModel):
    codes: list[str]
    note: str = "Сохраните коды: повторно они не показываются"


class TotpDisableRequest(BaseModel):
    password: str
    code: str
