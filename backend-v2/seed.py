"""Первичное наполнение БД (Спринт 1).

Создаёт роли, права и трёх сотрудников:

    000001 / admin        — администратор; 2FA пока не подключена,
                            пароль помечен как временный (must_change)
    000002 / operator123  — оператор; 2FA (TOTP) уже подключена,
                            секрет печатается в консоль
    000003 / —            — оператор без пароля: на нём проверяется
                            закрытая регистрация по коду

Запуск:  python seed.py  (из каталога backend-v2)
Повторный запуск безопасен: существующие записи не дублируются.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

import pyotp
from sqlalchemy import select

from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    new_totp_secret,
    totp_provisioning_uri,
)
from app.db.session import SessionLocal
from app.models import Credential, Employee, MfaFactor, Permission, Role

ROLES: dict[str, dict] = {
    "admin": {
        "name": "Администратор (инженер/диспетчер)",
        "description": "Правит схему, управляет сотрудниками, видит аудит",
    },
    "operator": {
        "name": "Оператор (рабочий/обходчик)",
        "description": "Смотрит схему, меняет статусы, добавляет фото и обходы",
    },
    "viewer": {"name": "Наблюдатель", "description": "Только просмотр"},
    "contractor": {
        "name": "Подрядчик",
        "description": "Ограниченный доступ к назначенным объектам (этап 2)",
    },
}

PERMISSIONS: dict[str, str] = {
    "topology.edit": "Правка топологии (связи, линии, порты)",
    "asset.create": "Создание объектов",
    "asset.delete": "Удаление объектов",
    "asset.status.edit": "Смена статуса и заземления",
    "asset.move": "Перемещение мобильных объектов",
    "media.create": "Загрузка фото и документов",
    "inspection.create": "Проведение обходов",
    "defect.manage": "Работа с дефектами",
    "employee.manage": "Управление сотрудниками и ролями",
    "audit.view": "Просмотр журнала аудита",
    "report.export": "Экспорт отчётов",
    "settings.edit": "Настройки карьера и справочников",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": set(PERMISSIONS.keys()),
    "operator": {
        "asset.status.edit",
        "asset.move",
        "media.create",
        "inspection.create",
        "defect.manage",
        "report.export",
    },
    "viewer": {"report.export"},
    "contractor": {"media.create", "inspection.create", "defect.manage"},
}


def ensure_roles(db) -> dict[str, Role]:
    result: dict[str, Role] = {}
    for code, meta in ROLES.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(id=uuid.uuid4(), code=code, name=meta["name"], description=meta["description"])
            db.add(role)
            db.flush()
        result[code] = role
    db.commit()
    return result


def ensure_permissions(db) -> dict[str, Permission]:
    result: dict[str, Permission] = {}
    for code, description in PERMISSIONS.items():
        perm = db.scalar(select(Permission).where(Permission.code == code))
        if perm is None:
            perm = Permission(id=uuid.uuid4(), code=code, description=description)
            db.add(perm)
            db.flush()
        result[code] = perm
    db.commit()
    return result


def ensure_role_permissions(db, roles: dict[str, Role], perms: dict[str, Permission]) -> None:
    for role_code, codes in ROLE_PERMISSIONS.items():
        role = roles[role_code]
        current = {p.code for p in role.permissions}
        for code in codes - current:
            role.permissions.append(perms[code])
    db.commit()


def ensure_employee(
    db,
    *,
    tab_no: str,
    full_name: str,
    role: Role,
    password: str | None,
    must_change: bool = False,
    position: str | None = None,
    telegram_id: int | None = None,
    otp_channel: str = "telegram",
) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.tab_no == tab_no))
    if employee is None:
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=tab_no,
            full_name=full_name,
            position=position,
            role_id=role.id,
            status="active",
            telegram_id=telegram_id,
            otp_channel=otp_channel,
        )
        db.add(employee)
        db.flush()
    if password and employee.credential is None:
        db.add(
            Credential(
                employee_id=employee.id,
                password_hash=hash_password(password),
                must_change=must_change,
                password_updated_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
    db.refresh(employee)
    return employee


def ensure_totp(db, employee: Employee) -> str:
    factor = db.scalar(
        select(MfaFactor).where(
            MfaFactor.employee_id == employee.id, MfaFactor.kind == "totp"
        )
    )
    if factor is not None and factor.confirmed_at is not None:
        return decrypt_secret(factor.secret_enc).strip()

    secret = new_totp_secret()
    if factor is None:
        factor = MfaFactor(id=uuid.uuid4(), employee_id=employee.id, kind="totp")
        db.add(factor)
    factor.secret_enc = encrypt_secret(secret)
    factor.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    return secret


def main() -> int:
    db = SessionLocal()
    try:
        roles = ensure_roles(db)
        perms = ensure_permissions(db)
        ensure_role_permissions(db, roles, perms)

        admin = ensure_employee(
            db,
            tab_no="000001",
            full_name="Администраторов Админ Админович",
            role=roles["admin"],
            password="admin",
            must_change=True,
            position="Главный энергетик",
        )
        operator = ensure_employee(
            db,
            tab_no="000002",
            full_name="Петров Пётр Петрович",
            role=roles["operator"],
            password="operator123",
            position="Электромонтёр",
            telegram_id=100000002,
        )
        ensure_employee(
            db,
            tab_no="000003",
            full_name="Сидоров Сидор Сидорович",
            role=roles["operator"],
            password=None,
            position="Обходчик",
            telegram_id=100000003,
        )

        secret = ensure_totp(db, operator)
        uri = totp_provisioning_uri(secret, tab_no=operator.tab_no)
        current_code = pyotp.TOTP(secret).now()

        print("\n" + "=" * 68)
        print("  База подготовлена. Учётные записи для проверки:")
        print("=" * 68)
        print("  000001 / admin         администратор (2FA выключена, пароль временный)")
        print("  000002 / operator123   оператор (2FA включена)")
        print("  000003 / —             без пароля: пройти регистрацию по коду")
        print("-" * 68)
        print("  TOTP для 000002 (добавить в Google Authenticator / Aegis):")
        print(f"  secret : {secret}")
        print(f"  uri    : {uri}")
        print(f"  code   : {current_code}   (действует 30 секунд)")
        print("=" * 68 + "\n")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
