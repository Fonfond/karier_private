"""Аварийный доступ (break glass): создание и ротация защищённой учётной записи.

Учётная запись `000000` с ролью admin предназначена для входа, когда обычные
администраторы недоступны. Пароль и TOTP-секрет генерируются скриптом,
печатаются один раз и хранятся на бумаге в сейфе.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret, hash_password
from app.models import Credential, Employee, MfaFactor, Role
from app.services import audit

BREAK_GLASS_TAB = "000000"
BREAK_GLASS_NAME = "Аварийный доступ (break glass)"
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_=+"
PASSWORD_LENGTH = 28


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role(db: Session) -> Role:
    role = db.scalar(select(Role).where(Role.code == "admin"))
    if role is None:
        raise RuntimeError("Роль admin не найдена — сначала выполните seed.py")
    return role


def _employee(db: Session) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.tab_no == BREAK_GLASS_TAB))
    if employee is None:
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=BREAK_GLASS_TAB,
            full_name=BREAK_GLASS_NAME,
            position="Аварийный администратор",
            department="Служба главного энергетика",
            otp_channel="manual",
            role_id=_role(db).id,
            status="active",
            is_break_glass=True,
        )
        db.add(employee)
        db.flush()
    else:
        employee.is_break_glass = True
        employee.status = "active"
        employee.role_id = _role(db).id
        if not employee.full_name:
            employee.full_name = BREAK_GLASS_NAME
    return employee


def provision(db: Session, *, rotate: bool = True) -> dict:
    """Создать или перевыпустить аварийную учётку. Возвращает новые секреты."""
    employee = _employee(db)
    password = generate_password()
    secret = pyotp.random_base32()

    credential = employee.credential
    if credential is None:
        credential = Credential(
            employee_id=employee.id,
            password_hash=hash_password(password),
            must_change=False,
            password_updated_at=_now(),
        )
        db.add(credential)
    else:
        credential.password_hash = hash_password(password)
        credential.must_change = False
        credential.failed_attempts = 0
        credential.locked_until = None
        credential.password_updated_at = _now()

    factor = db.scalar(select(MfaFactor).where(MfaFactor.employee_id == employee.id))
    if factor is None:
        db.add(
            MfaFactor(
                id=uuid.uuid4(),
                employee_id=employee.id,
                kind="totp",
                label="Аварийный доступ",
                secret_enc=encrypt_secret(secret),
                confirmed_at=_now(),
            )
        )
    else:
        factor.kind = "totp"
        factor.secret_enc = encrypt_secret(secret)
        factor.confirmed_at = _now()
        # новый секрет — сбрасываем защиту от повторного использования кода
        factor.last_counter = None
        factor.last_used_at = None

    db.commit()
    db.refresh(employee)

    from app.services.auth import revoke_all_sessions

    revoke_all_sessions(db, employee, reason="break_glass_rotated")

    audit.add(
        "break_glass.rotated" if rotate else "break_glass.created",
        entity="employee",
        entity_id=employee.id,
        detail="Выпущены новые пароль и TOTP-секрет аварийной учётной записи",
        payload={"tab_no": BREAK_GLASS_TAB, "break_glass": True},
    )
    audit.flush(db)

    return {
        "tab_no": BREAK_GLASS_TAB,
        "password": password,
        "secret": secret,
        "otpauth": pyotp.TOTP(secret).provisioning_uri(
            name=f"Karier {BREAK_GLASS_TAB}", issuer_name="Karier"
        ),
        "employee_id": str(employee.id),
    }


def disable(db: Session) -> None:
    employee = db.scalar(select(Employee).where(Employee.tab_no == BREAK_GLASS_TAB))
    if employee is None:
        return
    employee.status = "blocked"
    db.commit()
    from app.services.auth import revoke_all_sessions

    revoke_all_sessions(db, employee, reason="break_glass_disabled")
    audit.add(
        "break_glass.disabled",
        entity="employee",
        entity_id=employee.id,
        detail="Аварийная учётная запись заблокирована",
        payload={"tab_no": BREAK_GLASS_TAB, "break_glass": True},
    )
    audit.flush(db)


def ascii_qr(uri: str) -> str:
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make(fit=True)
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        qr.print_ascii(invert=True)
    return buffer.getvalue()
