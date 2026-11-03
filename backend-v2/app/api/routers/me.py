"""Профиль: данные пользователя, пароль, сессии, 2FA."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import settings
from app.core.errors import ApiError, not_found
from app.db.session import get_db
from app.models import AuthSession, Employee
from app.schemas.auth import (
    ChangePasswordRequest,
    RecoveryCodesOut,
    SessionOut,
    TotpConfirmRequest,
    TotpDisableRequest,
    TotpEnrollOut,
    UserOut,
)
from app.schemas.common import MessageOut
from app.services import audit
from app.services.auth import (
    change_password,
    confirm_totp_enrollment,
    create_session,
    disable_totp,
    mfa_factor,
    revoke_session,
    start_totp_enrollment,
    user_out,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut, summary="Текущий пользователь")
def me(user: Employee = Depends(current_user), db: Session = Depends(get_db)) -> UserOut:
    return user_out(db, user)


@router.post("/password", response_model=MessageOut, summary="Смена пароля")
def change_my_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    change_password(db, user, payload.current_password, payload.new_password)
    response.delete_cookie(key=settings.COOKIE_NAME, path=settings.COOKIE_PATH)
    return MessageOut(message="Пароль изменён. Войдите заново")


@router.get("/sessions", response_model=list[SessionOut], summary="Активные сессии")
def my_sessions(
    request: Request,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SessionOut]:
    rows = db.scalars(
        select(AuthSession)
        .where(AuthSession.employee_id == user.id, AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.created_at.desc())
    ).all()
    current_sid = str(getattr(request.state, "session_id", ""))
    return [
        SessionOut(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            ip=row.ip,
            user_agent=row.user_agent,
            current=str(row.id) == current_sid,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", response_model=MessageOut, summary="Отозвать сессию")
def revoke_my_session(
    session_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    session = db.get(AuthSession, session_id)
    if session is None or session.employee_id != user.id:
        raise not_found("Сессия не найдена")
    revoke_session(db, session, reason="user_revoked")
    audit.add("auth.session.revoked", entity="session", entity_id=session.id, detail="Отозвана пользователем")
    return MessageOut(message="Сессия отозвана")


# --- 2FA -------------------------------------------------------------------

@router.post("/mfa/totp/enroll", response_model=TotpEnrollOut, summary="Подключить TOTP")
def totp_enroll(
    user: Employee = Depends(current_user), db: Session = Depends(get_db)
) -> TotpEnrollOut:
    if mfa_factor(db, user.id) is not None:
        raise ApiError(409, "mfa.already_enabled", "Второй фактор уже подключён")
    secret, uri, qr = start_totp_enrollment(db, user)
    return TotpEnrollOut(secret=secret, otpauth_uri=uri, qr_svg=qr)


@router.post("/mfa/totp/confirm", response_model=RecoveryCodesOut, summary="Подтвердить TOTP")
def totp_confirm(
    payload: TotpConfirmRequest,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecoveryCodesOut:
    codes = confirm_totp_enrollment(db, user, payload.code)
    return RecoveryCodesOut(codes=codes)


@router.post("/mfa/totp/disable", response_model=MessageOut, summary="Отключить TOTP")
def totp_disable(
    payload: TotpDisableRequest,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    disable_totp(db, user, payload.password, payload.code)
    return MessageOut(message="Второй фактор отключён")
