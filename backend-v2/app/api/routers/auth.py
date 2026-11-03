"""Эндпоинты аутентификации: вход, 2FA, refresh, закрытая регистрация."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import client_ip, limiter
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    MfaRequiredOut,
    MfaVerifyRequest,
    RegisterCompleteRequest,
    RegisterStartOut,
    RegisterStartRequest,
    RegisterVerifyOut,
    RegisterVerifyRequest,
    TokenPairOut,
)
from app.services import audit
from app.services.auth import (
    GENERIC_REGISTER_MESSAGE,
    check_password,
    complete_registration,
    create_session,
    ensure_login_allowed,
    get_employee_by_tab,
    issue_mfa_challenge,
    mfa_factor,
    resolve_mfa_challenge,
    rotate_session,
    start_registration,
    user_out,
    verify_mfa_code,
    verify_registration,
)
from app.services.auth import session_by_id
from app.core.security import hash_refresh_token

router = APIRouter(prefix="/auth", tags=["auth"])


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.COOKIE_NAME, path=settings.COOKIE_PATH)


def _rate_limit_login(request: Request, tab_no: str) -> None:
    ip = client_ip(request)
    ok_ip = limiter.allow(
        f"login:ip:{ip}", limit=settings.RATE_LIMIT_LOGIN_PER_MINUTE, window_seconds=60
    )
    ok_tab = limiter.allow(
        f"login:tab:{tab_no}", limit=settings.RATE_LIMIT_LOGIN_PER_MINUTE, window_seconds=60
    )
    if not (ok_ip and ok_tab):
        audit.add(
            "auth.login.rate_limited",
            entity="employee",
            entity_id=tab_no,
            result="denied",
            detail="Превышен лимит попыток входа",
        )
        raise ApiError(
            429,
            "rate.limited",
            "Слишком много попыток входа. Подождите минуту",
            headers={"Retry-After": "60"},
        )


@router.post("/login", response_model=None, summary="Вход по табельному и паролю")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPairOut | MfaRequiredOut:
    _rate_limit_login(request, payload.tab_no)

    employee = get_employee_by_tab(db, payload.tab_no)
    employee = ensure_login_allowed(employee, tab_no=payload.tab_no)
    check_password(db, employee, payload.password)

    audit.set_actor(
        actor_id=employee.id,
        tab_no=employee.tab_no,
        role=employee.role.code if employee.role else "",
    )

    if mfa_factor(db, employee.id) is not None:
        audit.add(
            "auth.login.mfa_required",
            entity="employee",
            entity_id=employee.id,
            detail="Требуется второй фактор",
        )
        return MfaRequiredOut(
            challenge_token=issue_mfa_challenge(employee),
            expires_in=settings.MFA_CHALLENGE_TTL_MIN * 60,
            full_name=employee.full_name,
        )

    tokens = create_session(db, employee, request)
    set_refresh_cookie(response, tokens.refresh_token)
    audit.add(
        "auth.login.success",
        entity="employee",
        entity_id=employee.id,
        detail="Вход без второго фактора",
    )
    return TokenPairOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=user_out(db, employee),
    )


@router.post("/mfa/verify", response_model=TokenPairOut, summary="Проверка кода 2FA")
def mfa_verify(
    payload: MfaVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPairOut:
    employee = resolve_mfa_challenge(db, payload.challenge_token)

    if not limiter.allow(
        f"mfa:{employee.id}:{client_ip(request)}",
        limit=settings.RATE_LIMIT_LOGIN_PER_MINUTE,
        window_seconds=60,
    ):
        raise ApiError(429, "rate.limited", "Слишком много попыток. Подождите минуту")

    if not verify_mfa_code(db, employee, payload.code):
        audit.add(
            "auth.mfa.failed",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail="Неверный код 2FA",
        )
        raise ApiError(400, "auth.mfa_invalid", "Неверный код подтверждения")

    audit.set_actor(
        actor_id=employee.id,
        tab_no=employee.tab_no,
        role=employee.role.code if employee.role else "",
    )
    tokens = create_session(db, employee, request)
    set_refresh_cookie(response, tokens.refresh_token)
    audit.add(
        "auth.login.success",
        entity="employee",
        entity_id=employee.id,
        detail="Вход с подтверждением 2FA",
    )
    return TokenPairOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=user_out(db, employee),
    )


@router.post("/refresh", response_model=TokenPairOut, summary="Обновить access-токен")
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPairOut:
    raw = request.cookies.get(settings.COOKIE_NAME)
    if not raw:
        raise ApiError(401, "auth.no_session", "Нет активной сессии")

    tokens = rotate_session(db, raw, request)
    set_refresh_cookie(response, tokens.refresh_token)
    employee = tokens.session.employee
    return TokenPairOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=user_out(db, employee),
    )


@router.post("/logout", summary="Выход (текущая сессия)")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    raw = request.cookies.get(settings.COOKIE_NAME)
    if raw:
        from sqlalchemy import select

        from app.models import AuthSession
        from app.services.auth import revoke_session

        session = db.scalar(
            select(AuthSession).where(AuthSession.refresh_hash == hash_refresh_token(raw))
        )
        if session is not None:
            revoke_session(db, session, reason="logout")
            audit.add(
                "auth.logout",
                entity="session",
                entity_id=session.id,
                detail="Выход",
            )
    clear_refresh_cookie(response)
    return {"message": "Вы вышли из системы"}


@router.post("/register/start", response_model=RegisterStartOut, summary="Шаг 1: запрос кода")
def register_start(payload: RegisterStartRequest, request: Request, db: Session = Depends(get_db)):
    if not limiter.allow(
        f"register:ip:{client_ip(request)}",
        limit=settings.RATE_LIMIT_REGISTER_PER_HOUR,
        window_seconds=3600,
    ):
        raise ApiError(429, "rate.limited", "Слишком много запросов кода. Попробуйте позже")

    data = start_registration(db, payload.tab_no)
    return RegisterStartOut(**data)


@router.post("/register/verify", response_model=RegisterVerifyOut, summary="Шаг 2: проверка кода")
def register_verify(payload: RegisterVerifyRequest, db: Session = Depends(get_db)):
    token = verify_registration(db, payload.tab_no, payload.code)
    return RegisterVerifyOut(
        setup_token=token, expires_in=settings.PASSWORD_RESET_TTL_MIN * 60
    )


@router.post("/register/complete", response_model=TokenPairOut, summary="Шаг 3: установка пароля")
def register_complete(
    payload: RegisterCompleteRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPairOut:
    employee = complete_registration(db, payload.setup_token, payload.password)
    tokens = create_session(db, employee, request)
    set_refresh_cookie(response, tokens.refresh_token)
    audit.set_actor(
        actor_id=employee.id,
        tab_no=employee.tab_no,
        role=employee.role.code if employee.role else "",
    )
    return TokenPairOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=user_out(db, employee),
    )
