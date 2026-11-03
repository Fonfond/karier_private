"""Криптография и токены: Argon2id, JWT, TOTP, шифрование секретов."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

TokenType = Literal["access", "mfa_challenge", "password_reset", "onboarding", "document"]

# --- пароли ---------------------------------------------------------------

# Параметры OWASP для Argon2id (19 MiB / 2 итерации — минимальный профиль,
# для сервера поднимаем память до 64 MiB).
_password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=64 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

COMMON_PASSWORDS = {
    "123456", "12345678", "qwerty", "qwerty123", "password", "password1",
    "admin", "admin123", "administrator", "111111", "123123", "123456789",
    "000000", "qwertyuiop", "iloveyou", "monkey", "dragon", "letmein",
    "welcome", "sunshine", "princess", "football", "charlie", "aa123456",
    "karer", "karier", "karier2026", "gornyak", "gornyak2026",
}


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_policy(password: str, *, tab_no: str = "", full_name: str = "") -> list[str]:
    """Вернуть список нарушений политики (пустой список — пароль допустим)."""
    problems: list[str] = []
    if len(password) < 10:
        problems.append("Пароль должен быть не короче 10 символов")
    if len(password) > 128:
        problems.append("Пароль слишком длинный (максимум 128 символов)")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("Пароль слишком распространённый")
    if password.lower() == tab_no.lower():
        problems.append("Пароль не должен совпадать с табельным номером")
    name_parts = [p.lower() for p in full_name.split() if len(p) >= 4]
    if any(part in password.lower() for part in name_parts):
        problems.append("Пароль не должен содержать фамилию или имя")
    if password.isdigit():
        problems.append("Пароль не должен состоять только из цифр")
    return problems


# --- JWT ------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    subject: str,
    token_type: TokenType,
    ttl: timedelta,
    **claims: Any,
) -> str:
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + ttl).timestamp()),
        "jti": secrets.token_hex(8),
        **claims,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(f"Ожидался токен типа {expected_type}")
    return payload


def create_access_token(employee_id: str, *, role: str, session_id: str) -> str:
    return create_token(
        employee_id,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
        role=role,
        sid=session_id,
    )


def create_mfa_challenge(employee_id: str) -> str:
    return create_token(
        employee_id,
        "mfa_challenge",
        timedelta(minutes=settings.MFA_CHALLENGE_TTL_MIN),
    )


def create_password_reset_token(employee_id: str, *, purpose: str) -> str:
    return create_token(
        employee_id,
        "password_reset",
        timedelta(minutes=settings.PASSWORD_RESET_TTL_MIN),
        purpose=purpose,
    )


def create_document_token(document_id: str, *, employee_id: str) -> str:
    """Короткоживущая ссылка на файл документа (для iframe/img без заголовков)."""
    return create_token(
        document_id,
        "document",
        timedelta(minutes=settings.DOCUMENT_URL_TTL_MIN),
        employee_id=employee_id,
    )


# --- refresh-токены (непрозрачные, хранятся хэшем) -------------------------

def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# --- TOTP -----------------------------------------------------------------

def new_totp_secret() -> str:
    return pyotp.random_base32(length=32)


def totp_provisioning_uri(secret: str, *, tab_no: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=f"{tab_no}@karier", issuer_name="Карьер · Электроснабжение"
    )


def verify_totp(secret: str, code: str, *, last_counter: int | None = None) -> int | None:
    """Проверить код TOTP. Возвращает использованный счётчик или None.

    Допускается расхождение часов ±1 шаг (30 c). Повторное использование
    того же счётчика запрещено (защита от replay).
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = datetime.now(timezone.utc)
    for drift in (-1, 0, 1):
        moment = now + timedelta(seconds=30 * drift)
        if totp.verify(code, for_time=moment, valid_window=0):
            counter = int(moment.timestamp()) // 30
            if last_counter is not None and counter <= last_counter:
                return None
            return counter
    return None


# --- шифрование TOTP-секретов ---------------------------------------------

def _mfa_key() -> bytes:
    return hashlib.sha256(f"{settings.SECRET_KEY}:mfa-secret-v1".encode("utf-8")).digest()


def encrypt_secret(plain: str) -> bytes:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_mfa_key()).encrypt(nonce, plain.encode("utf-8"), b"mfa")
    return base64.urlsafe_b64encode(nonce + ciphertext)


def decrypt_secret(blob: bytes) -> str:
    raw = base64.urlsafe_b64decode(blob)
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(_mfa_key()).decrypt(nonce, ciphertext, b"mfa").decode("utf-8")


# --- одноразовые коды ------------------------------------------------------

def new_numeric_code(length: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part = lambda: "".join(secrets.choice(alphabet) for _ in range(4))  # noqa: E731
    return f"{part()}-{part()}"


def normalize_recovery_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def code_hash(code: str) -> str:
    return _password_hasher.hash(code)


def verify_code(code_hash_value: str, code: str) -> bool:
    return verify_password(code_hash_value, code)
