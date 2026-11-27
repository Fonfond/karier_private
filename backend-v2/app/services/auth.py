"""Бизнес-логика доступа: вход, 2FA, закрытая регистрация, сессии."""

from __future__ import annotations

import base64
import io
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import qrcode
import qrcode.image.svg
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import client_ip
from app.core.security import (
    create_access_token,
    create_mfa_challenge,
    create_password_reset_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_numeric_code,
    new_recovery_code,
    new_refresh_token,
    new_totp_secret,
    normalize_recovery_code,
    totp_provisioning_uri,
    validate_password_policy,
    verify_code,
    verify_password,
    verify_totp,
    code_hash,
)
from app.models import (
    AuthSession,
    Credential,
    Employee,
    MfaFactor,
    OnboardingToken,
    RecoveryCode,
    Role,
)
from app.schemas.auth import UserOut
from app.services import audit


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tab(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "")


# --- выборки ---------------------------------------------------------------

def get_employee(db: Session, employee_id: uuid.UUID | str) -> Employee | None:
    return db.get(Employee, employee_id)


def get_employee_by_tab(db: Session, tab_no: str) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.tab_no == normalize_tab(tab_no)))


def get_role(db: Session, code: str) -> Role | None:
    return db.scalar(select(Role).where(Role.code == code))


def permissions_of(employee: Employee) -> list[str]:
    if employee.role is None:
        return []
    return sorted({p.code for p in employee.role.permissions})


def mfa_factor(db: Session, employee_id: uuid.UUID) -> MfaFactor | None:
    return db.scalar(
        select(MfaFactor).where(
            MfaFactor.employee_id == employee_id,
            MfaFactor.kind == "totp",
            MfaFactor.confirmed_at.is_not(None),
            MfaFactor.revoked_at.is_(None),
        )
    )


def user_out(db: Session, employee: Employee) -> UserOut:
    credential = employee.credential
    return UserOut(
        id=employee.id,
        tab_no=employee.tab_no,
        full_name=employee.full_name,
        position=employee.position,
        department=employee.department,
        role=employee.role.code if employee.role else "",
        permissions=permissions_of(employee),
        status=employee.status,
        mfa_enabled=mfa_factor(db, employee.id) is not None,
        must_change_password=bool(credential and credential.must_change),
        last_login_at=credential.last_login_at if credential else None,
    )


# --- проверки доступа ------------------------------------------------------

def ensure_login_allowed(employee: Employee | None, *, tab_no: str) -> Employee:
    if employee is None:
        audit.add(
            "auth.login.unknown_tab",
            entity="employee",
            entity_id=tab_no,
            result="denied",
            detail="Табельный номер не найден в справочнике",
        )
        raise ApiError(401, "auth.invalid_credentials", "Неверный табельный номер или пароль")

    if employee.status != "active":
        audit.add(
            "auth.login.blocked",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail=f"Статус сотрудника: {employee.status}",
        )
        raise ApiError(403, "auth.not_allowed", "Доступ запрещён. Обратитесь к администратору")

    if employee.access_until and employee.access_until < now():
        audit.add(
            "auth.login.access_expired",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail="Истёк срок доступа",
        )
        raise ApiError(403, "auth.not_allowed", "Срок доступа истёк. Обратитесь к администратору")

    return employee


def _lock_duration(attempts: int) -> int:
    """Длительность блокировки в минутах по числу неудачных попыток."""
    level = attempts // settings.MAX_FAILED_ATTEMPTS
    steps = settings.LOCKOUT_MINUTES
    index = min(max(level - 1, 0), len(steps) - 1)
    return steps[index]


def check_password(db: Session, employee: Employee, password: str) -> Credential:
    credential = employee.credential
    if credential is None:
        audit.add(
            "auth.login.no_password",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail="Пароль не установлен (регистрация не завершена)",
        )
        raise ApiError(401, "auth.invalid_credentials", "Неверный табельный номер или пароль")

    if credential.locked_until and credential.locked_until > now():
        retry_after = int((credential.locked_until - now()).total_seconds())
        audit.add(
            "auth.login.locked",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail=f"Блокировка ещё {retry_after} c",
        )
        raise ApiError(
            423,
            "auth.locked",
            "Слишком много неудачных попыток. Попробуйте позже",
            headers={"Retry-After": str(retry_after)},
        )

    if not verify_password(credential.password_hash, password):
        credential.failed_attempts = (credential.failed_attempts or 0) + 1
        attempts = credential.failed_attempts
        if attempts % settings.MAX_FAILED_ATTEMPTS == 0:
            credential.locked_until = now() + timedelta(minutes=_lock_duration(attempts))
            audit.add(
                "auth.login.lockout",
                entity="employee",
                entity_id=employee.id,
                result="denied",
                detail=f"Блокировка после {attempts} неудачных попыток",
            )
        db.commit()
        audit.add(
            "auth.login.failed_password",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail=f"Неверный пароль, попытка {attempts}",
        )
        raise ApiError(401, "auth.invalid_credentials", "Неверный табельный номер или пароль")

    if needs_rehash(credential.password_hash):
        credential.password_hash = hash_password(password)

    credential.failed_attempts = 0
    credential.locked_until = None
    credential.last_login_at = now()
    db.commit()
    return credential


# --- сессии ----------------------------------------------------------------

def _request_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    return client_ip(request), (request.headers.get("user-agent") or "")[:255]


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    session: AuthSession
    expires_in: int


def create_session(
    db: Session,
    employee: Employee,
    request: Request | None = None,
    *,
    family_id: uuid.UUID | None = None,
) -> IssuedTokens:
    refresh = new_refresh_token()
    ip, ua = _request_meta(request)
    session = AuthSession(
        id=uuid.uuid4(),
        employee_id=employee.id,
        family_id=family_id or uuid.uuid4(),
        refresh_hash=hash_refresh_token(refresh),
        refresh_expires_at=now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        last_seen_at=now(),
        ip=ip,
        user_agent=ua,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    access = create_access_token(
        str(employee.id),
        role=employee.role.code if employee.role else "",
        session_id=str(session.id),
    )
    return IssuedTokens(access, refresh, session, settings.ACCESS_TOKEN_TTL_MIN * 60)


def rotate_session(db: Session, refresh_token: str, request: Request | None = None) -> IssuedTokens:
    token_hash = hash_refresh_token(refresh_token)
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_hash == token_hash))

    if session is None:
        # Возможно, это старый (уже ротированный) токен.
        reused = db.scalar(
            select(AuthSession).where(AuthSession.prev_refresh_hash == token_hash)
        )
        if reused is not None:
            grace = settings.REFRESH_REUSE_GRACE_SECONDS
            recent = (
                reused.last_seen_at is not None
                and (now() - reused.last_seen_at).total_seconds() <= grace
            )
            if reused.revoked_at is None and recent:
                # гонка вкладок: токен уже ротирован секунды назад — не наказываем,
                # выдаём новую пару на той же сессии
                audit.add(
                    "auth.refresh.race",
                    entity="session",
                    entity_id=reused.id,
                    detail="Повторное использование токена в пределах окна — считаем гонкой вкладок",
                )
                session = reused
            else:
                _revoke_family(db, reused, reason="reuse_detected")
                audit.add(
                    "auth.refresh.reuse_detected",
                    entity="session",
                    entity_id=reused.id,
                    result="denied",
                    detail="Повторно использован старый refresh-токен, семейство отозвано",
                )
        if session is None:
            raise ApiError(401, "auth.session_expired", "Сессия истекла, войдите заново")

    if session.revoked_at is not None:
        raise ApiError(401, "auth.session_expired", "Сессия отозвана, войдите заново")

    if session.refresh_expires_at < now():
        _revoke_family(db, session, reason="expired")
        raise ApiError(401, "auth.session_expired", "Сессия истекла, войдите заново")

    employee = session.employee
    if employee.status != "active":
        _revoke_family(db, session, reason="employee_blocked")
        raise ApiError(403, "auth.not_allowed", "Доступ запрещён")

    new_token = new_refresh_token()
    session.prev_refresh_hash = session.refresh_hash
    session.refresh_hash = hash_refresh_token(new_token)
    session.refresh_expires_at = now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
    session.last_seen_at = now()
    ip, ua = _request_meta(request)
    session.ip = ip or session.ip
    session.user_agent = ua or session.user_agent
    db.commit()

    access = create_access_token(
        str(employee.id),
        role=employee.role.code if employee.role else "",
        session_id=str(session.id),
    )
    return IssuedTokens(access, new_token, session, settings.ACCESS_TOKEN_TTL_MIN * 60)


def _revoke_family(db: Session, session: AuthSession, *, reason: str) -> None:
    db.execute(
        AuthSession.__table__.update()
        .where(AuthSession.family_id == session.family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now(), revoke_reason=reason)
    )
    db.commit()


def revoke_session(db: Session, session: AuthSession, *, reason: str = "logout") -> None:
    session.revoked_at = now()
    session.revoke_reason = reason
    db.commit()


def revoke_all_sessions(db: Session, employee: Employee, *, reason: str = "logout_all") -> int:
    result = db.execute(
        AuthSession.__table__.update()
        .where(AuthSession.employee_id == employee.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now(), revoke_reason=reason)
    )
    db.commit()
    return result.rowcount or 0


def session_by_id(db: Session, session_id: str | uuid.UUID) -> AuthSession | None:
    try:
        return db.get(AuthSession, uuid.UUID(str(session_id)))
    except (ValueError, AttributeError):
        return None


# --- 2FA -------------------------------------------------------------------

def issue_mfa_challenge(employee: Employee) -> str:
    return create_mfa_challenge(str(employee.id))


def verify_mfa_code(db: Session, employee: Employee, code: str) -> bool:
    factor = mfa_factor(db, employee.id)
    if factor is None:
        return False

    # 1) TOTP
    secret = decrypt_secret(factor.secret_enc)
    counter = verify_totp(secret, code, last_counter=factor.last_counter)
    if counter is not None:
        factor.last_counter = counter
        factor.last_used_at = now()
        db.commit()
        return True

    # 2) резервный код
    normalized = normalize_recovery_code(code)
    if "-" in normalized or len(normalized) >= 8:
        rows = db.scalars(
            select(RecoveryCode).where(
                RecoveryCode.employee_id == employee.id, RecoveryCode.used_at.is_(None)
            )
        ).all()
        for row in rows:
            if verify_code(row.code_hash, normalized):
                row.used_at = now()
                factor.last_used_at = now()
                db.commit()
                audit.add(
                    "auth.mfa.recovery_code_used",
                    entity="employee",
                    entity_id=employee.id,
                    detail="Использован резервный код",
                )
                return True
    return False


def resolve_mfa_challenge(db: Session, challenge_token: str) -> Employee:
    try:
        payload = decode_token(challenge_token, "mfa_challenge")
    except Exception as exc:  # noqa: BLE001
        raise ApiError(401, "auth.mfa_expired", "Время подтверждения истекло, войдите заново") from exc
    employee = get_employee(db, payload["sub"])
    if employee is None:
        raise ApiError(401, "auth.mfa_expired", "Пользователь не найден")
    return employee


# --- TOTP enrollment -------------------------------------------------------

def start_totp_enrollment(db: Session, employee: Employee) -> tuple[str, str, str]:
    secret = new_totp_secret()
    factor = db.scalar(
        select(MfaFactor).where(
            MfaFactor.employee_id == employee.id,
            MfaFactor.kind == "totp",
            MfaFactor.confirmed_at.is_(None),
        )
    )
    if factor is None:
        factor = MfaFactor(id=uuid.uuid4(), employee_id=employee.id, kind="totp")
        db.add(factor)
    factor.secret_enc = encrypt_secret(secret)
    factor.revoked_at = None
    db.commit()

    uri = totp_provisioning_uri(secret, tab_no=employee.tab_no)
    return secret, uri, _qr_data_uri(uri)


def _qr_data_uri(uri: str) -> str:
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def confirm_totp_enrollment(db: Session, employee: Employee, code: str) -> list[str]:
    factor = db.scalar(
        select(MfaFactor).where(
            MfaFactor.employee_id == employee.id,
            MfaFactor.kind == "totp",
            MfaFactor.confirmed_at.is_(None),
            MfaFactor.revoked_at.is_(None),
        )
    )
    if factor is None:
        raise ApiError(400, "mfa.enroll_not_started", "Сначала запросите подключение 2FA")

    secret = decrypt_secret(factor.secret_enc)
    counter = verify_totp(secret, code)
    if counter is None:
        raise ApiError(400, "mfa.invalid_code", "Неверный код. Проверьте время на телефоне")

    factor.confirmed_at = now()
    factor.last_counter = counter
    factor.last_used_at = now()

    # перевыпускаем резервные коды
    db.execute(
        RecoveryCode.__table__.delete().where(RecoveryCode.employee_id == employee.id)
    )
    plain_codes = [new_recovery_code() for _ in range(10)]
    for plain in plain_codes:
        db.add(RecoveryCode(employee_id=employee.id, code_hash=code_hash(plain)))
    db.commit()

    audit.add(
        "mfa.totp.enabled",
        entity="employee",
        entity_id=employee.id,
        detail="Включён второй фактор (TOTP)",
    )
    return plain_codes


def disable_totp(db: Session, employee: Employee, password: str, code: str) -> None:
    credential = employee.credential
    if credential is None or not verify_password(credential.password_hash, password):
        raise ApiError(401, "auth.invalid_credentials", "Неверный пароль")
    if not verify_mfa_code(db, employee, code):
        raise ApiError(400, "mfa.invalid_code", "Неверный код подтверждения")

    db.execute(
        MfaFactor.__table__.update()
        .where(MfaFactor.employee_id == employee.id, MfaFactor.kind == "totp")
        .values(revoked_at=now())
    )
    db.execute(
        RecoveryCode.__table__.delete().where(RecoveryCode.employee_id == employee.id)
    )
    db.commit()
    audit.add(
        "mfa.totp.disabled",
        entity="employee",
        entity_id=employee.id,
        detail="Отключён второй фактор",
    )


# --- закрытая регистрация --------------------------------------------------

GENERIC_REGISTER_MESSAGE = "Если табельный номер найден, код отправлен"

# Срок жизни кода первичной регистрации. Код выдаёт администратор вручную
# (POST /api/employees/{id}/otp); фиксированное значение, чтобы срок не зависел
# от .env и был одинаковым на стенде и в prod.
REGISTRATION_CODE_TTL_MIN = 10


def start_registration(db: Session, tab_no: str) -> dict:
    employee = get_employee_by_tab(db, tab_no)
    if employee is None or employee.status != "active":
        audit.add(
            "auth.register.start_denied",
            entity="employee",
            entity_id=normalize_tab(tab_no),
            result="denied",
            detail="Нет активной карточки сотрудника",
        )
        return {
            "delivery": "telegram",
            "delivery_target": None,
            "expires_in": 0,
            "next_step": "code_sent",
        }

    if employee.credential is not None:
        audit.add(
            "auth.register.already_registered",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail="Пароль уже установлен",
        )
        return {
            "delivery": employee.otp_channel or "telegram",
            "delivery_target": None,
            "expires_in": 0,
            "next_step": "already_registered",
        }

    # Код больше НЕ генерируется и НЕ возвращается в ответе: его выдаёт
    # администратор через POST /api/employees/{id}/otp. Здесь только сообщаем,
    # есть ли уже выданный и ещё живой код.
    active = db.scalar(
        select(OnboardingToken)
        .where(
            OnboardingToken.employee_id == employee.id,
            OnboardingToken.consumed_at.is_(None),
            OnboardingToken.expires_at > now(),
        )
        .order_by(OnboardingToken.created_at.desc())
        .limit(1)
    )
    audit.add(
        "auth.register.code_required",
        entity="employee",
        entity_id=employee.id,
        detail="Код выдаёт администратор",
    )
    return {
        "delivery": employee.otp_channel or "telegram",
        "delivery_target": None,
        "expires_in": int((active.expires_at - now()).total_seconds()) if active else 0,
        "next_step": "code_required",
    }


def issue_registration_code(db: Session, employee: Employee) -> dict:
    """Выдать одноразовый код первичной регистрации (только администратор).

    Код возвращается вызывающему РОВНО ОДИН РАЗ и нигде не сохраняется открытым:
    в БД лежит только `code_hash`. Повторная выдача гасит все прежние коды;
    срок жизни — `REGISTRATION_CODE_TTL_MIN` (10 минут).
    """
    if employee.credential is not None:
        raise ApiError(409, "employee.already_registered", "Сотрудник уже зарегистрирован")
    if employee.status != "active":
        raise ApiError(409, "employee.inactive", "Сотрудник неактивен")

    # Гасим прежние коды: действующим остаётся только что выданный.
    db.execute(
        OnboardingToken.__table__.update()
        .where(
            OnboardingToken.employee_id == employee.id,
            OnboardingToken.consumed_at.is_(None),
        )
        .values(consumed_at=now())
    )

    code = new_numeric_code(6)
    expires_at = now() + timedelta(minutes=REGISTRATION_CODE_TTL_MIN)
    token = OnboardingToken(
        id=uuid.uuid4(),
        employee_id=employee.id,
        channel="manual",
        code_hash=code_hash(code),
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()

    audit.add(
        "auth.register.code_issued",
        entity="employee",
        entity_id=employee.id,
        detail=f"Код выдан администратором, срок {REGISTRATION_CODE_TTL_MIN} мин",
        payload={"channel": "manual"},
    )
    return {
        "code": code,
        "expires_at": expires_at,
        "expires_in": REGISTRATION_CODE_TTL_MIN * 60,
        "tab_no": employee.tab_no,
    }


def verify_registration(db: Session, tab_no: str, code: str) -> str:
    employee = get_employee_by_tab(db, tab_no)
    if employee is None:
        raise ApiError(400, "auth.code_invalid", "Код неверный или истёк")

    token = db.scalar(
        select(OnboardingToken)
        .where(
            OnboardingToken.employee_id == employee.id,
            OnboardingToken.consumed_at.is_(None),
        )
        .order_by(OnboardingToken.created_at.desc())
        .limit(1)
    )
    if token is None or token.expires_at < now():
        raise ApiError(400, "auth.code_expired", "Код истёк. Запросите новый")

    if token.attempts >= 5:
        token.consumed_at = now()
        db.commit()
        raise ApiError(429, "auth.code_attempts", "Слишком много попыток. Запросите новый код")

    token.attempts += 1
    db.commit()

    if not verify_code(token.code_hash, code.strip()):
        audit.add(
            "auth.register.bad_code",
            entity="employee",
            entity_id=employee.id,
            result="denied",
            detail=f"Попытка {token.attempts}",
        )
        raise ApiError(400, "auth.code_invalid", "Код неверный или истёк")

    token.consumed_at = now()
    db.commit()
    audit.add(
        "auth.register.code_verified",
        entity="employee",
        entity_id=employee.id,
        detail="Код подтверждён",
    )
    return create_password_reset_token(str(employee.id), purpose="registration")


def complete_registration(db: Session, setup_token: str, password: str) -> Employee:
    try:
        payload = decode_token(setup_token, "password_reset")
    except Exception as exc:  # noqa: BLE001
        raise ApiError(400, "auth.setup_expired", "Время установки пароля истекло") from exc
    if payload.get("purpose") != "registration":
        raise ApiError(400, "auth.setup_expired", "Некорректный токен установки пароля")

    employee = get_employee(db, payload["sub"])
    if employee is None:
        raise ApiError(400, "auth.setup_expired", "Сотрудник не найден")
    if employee.credential is not None:
        raise ApiError(409, "auth.already_registered", "Пароль уже установлен. Войдите")

    problems = validate_password_policy(
        password, tab_no=employee.tab_no, full_name=employee.full_name
    )
    if problems:
        raise ApiError(400, "validation.failed", problems[0], fields={"password": problems[0]})

    db.add(
        Credential(
            employee_id=employee.id,
            password_hash=hash_password(password),
            must_change=False,
            password_updated_at=now(),
        )
    )
    db.commit()
    db.refresh(employee)

    audit.add(
        "auth.register.completed",
        entity="employee",
        entity_id=employee.id,
        detail="Пароль установлен",
    )
    return employee


# --- администрирование -----------------------------------------------------

def set_temp_password(db: Session, employee: Employee) -> str:
    temp = f"Karier-{secrets.token_hex(4).upper()}"
    credential = employee.credential
    if credential is None:
        credential = Credential(employee_id=employee.id, password_hash=hash_password(temp))
        db.add(credential)
    else:
        credential.password_hash = hash_password(temp)
        credential.must_change = True
        credential.failed_attempts = 0
        credential.locked_until = None
        credential.password_updated_at = now()
    revoke_all_sessions(db, employee, reason="password_reset")
    db.commit()
    audit.add(
        "employee.password_reset",
        entity="employee",
        entity_id=employee.id,
        detail="Пароль сброшен администратором",
    )
    return temp


def change_password(db: Session, employee: Employee, current: str, new: str) -> None:
    credential = employee.credential
    if credential is None or not verify_password(credential.password_hash, current):
        raise ApiError(401, "auth.invalid_credentials", "Текущий пароль неверен")

    problems = validate_password_policy(new, tab_no=employee.tab_no, full_name=employee.full_name)
    if problems:
        raise ApiError(400, "validation.failed", problems[0], fields={"password": problems[0]})
    if verify_password(credential.password_hash, new):
        raise ApiError(400, "validation.failed", "Новый пароль совпадает с текущим")

    credential.password_hash = hash_password(new)
    credential.must_change = False
    credential.password_updated_at = now()
    db.commit()
    revoke_all_sessions(db, employee, reason="password_changed")
    audit.add(
        "auth.password_changed",
        entity="employee",
        entity_id=employee.id,
        detail="Пользователь сменил пароль",
    )


def count_employees(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Employee)) or 0
