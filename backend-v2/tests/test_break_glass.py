"""Тесты аварийного доступа (break glass)."""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import desc, select

from app.db.session import SessionLocal
from app.models import AuditLog, Employee
from app.services import break_glass as bg


def _provision() -> dict:
    db = SessionLocal()
    try:
        return bg.provision(db, rotate=True)
    finally:
        db.close()


def _login(client, password: str, secret: str) -> dict:
    step1 = client.post("/api/auth/login", json={"tab_no": "000000", "password": password})
    assert step1.status_code == 200, step1.text
    body = step1.json()
    assert body.get("mfa_required") is True, body

    code = pyotp.TOTP(secret).now()
    step2 = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": body["challenge_token"], "code": code},
    )
    assert step2.status_code == 200, step2.text
    return step2.json()


def test_break_glass_login_and_audit_flag(client, admin_headers):
    data = _provision()
    tokens = _login(client, data["password"], data["secret"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # обычное действие, которое пишется в аудит
    assets = client.get("/api/assets?limit=10", headers=headers).json()["items"]
    target = next(item for item in assets if item["status"] == "on")
    response = client.post(
        f"/api/assets/{target['id']}/state",
        headers=headers,
        json={"status": "off", "reason": "проверка аварийного доступа"},
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        employee = db.scalar(select(Employee).where(Employee.tab_no == "000000"))
        assert employee is not None and employee.is_break_glass is True
        rows = db.scalars(
            select(AuditLog)
            .where(AuditLog.actor_id == employee.id)
            .order_by(desc(AuditLog.at))
            .limit(5)
        ).all()
        assert rows, "действия должны попасть в журнал"
        assert any((row.payload or {}).get("break_glass") is True for row in rows), (
            "в журнале должна быть метка break_glass"
        )
    finally:
        db.close()

    # возвращаем состояние
    client.post(
        f"/api/assets/{target['id']}/state",
        headers=admin_headers,
        json={"status": "on", "reason": "восстановление после проверки"},
    )


def test_break_glass_protected_from_ui_actions(client, admin_headers):
    _provision()
    db = SessionLocal()
    try:
        employee = db.scalar(select(Employee).where(Employee.tab_no == "000000"))
        employee_id = str(employee.id)
    finally:
        db.close()

    for path, method in (
        (f"/api/employees/{employee_id}/block", "post"),
        (f"/api/employees/{employee_id}", "delete"),
        (f"/api/employees/{employee_id}/permanent", "delete"),
    ):
        response = getattr(client, method)(path, headers=admin_headers)
        assert response.status_code == 400, (path, response.text)
        assert response.json()["code"] == "employee.break_glass_protected"

    # смена роли через PATCH тоже запрещена
    response = client.patch(
        f"/api/employees/{employee_id}", headers=admin_headers, json={"role": "viewer"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "employee.break_glass_protected"


def test_break_glass_listed_with_flag(client, admin_headers):
    _provision()
    employees = client.get("/api/employees?limit=200", headers=admin_headers).json()["items"]
    guard = next(item for item in employees if item["tab_no"] == "000000")
    assert guard["is_break_glass"] is True
    assert guard["role"] == "admin"


def test_break_glass_reset_changes_secret(client):
    first = _provision()
    second = _provision()
    assert first["password"] != second["password"]
    assert first["secret"] != second["secret"]

    # старый пароль больше не действует
    response = client.post(
        "/api/auth/login", json={"tab_no": "000000", "password": first["password"]}
    )
    assert response.status_code == 401

    _login(client, second["password"], second["secret"])


def test_break_glass_disable_blocks_login(client):
    data = _provision()
    db = SessionLocal()
    try:
        bg.disable(db)
    finally:
        db.close()

    response = client.post(
        "/api/auth/login", json={"tab_no": "000000", "password": data["password"]}
    )
    assert response.status_code in (401, 403)

    # возвращаем в рабочее состояние
    _provision()
