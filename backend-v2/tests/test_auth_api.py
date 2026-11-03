"""API-тесты Спринта 1: вход, 2FA, роли, регистрация, аудит."""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.models import Employee, MfaFactor


def _reset_totp_counter(tab_no: str) -> None:
    db = SessionLocal()
    try:
        employee = db.scalar(select(Employee).where(Employee.tab_no == tab_no))
        if employee is not None:
            db.execute(
                update(MfaFactor)
                .where(MfaFactor.employee_id == employee.id)
                .values(last_counter=None)
            )
            db.commit()
    finally:
        db.close()


def test_health(client):
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_login_admin_success(client):
    response = client.post("/api/auth/login", json={"tab_no": "000001", "password": "admin"})
    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is False
    assert body["user"]["role"] == "admin"
    assert body["user"]["tab_no"] == "000001"
    assert "employee.manage" in body["user"]["permissions"]


def test_login_wrong_password(client):
    response = client.post("/api/auth/login", json={"tab_no": "000001", "password": "nope-nope"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.invalid_credentials"


def test_login_unknown_tab_same_message(client):
    response = client.post("/api/auth/login", json={"tab_no": "999999", "password": "whatever"})
    assert response.status_code == 401
    # ответ не должен раскрывать, существует ли табельный
    assert response.json()["detail"] == "Неверный табельный номер или пароль"


def test_operator_cannot_list_employees(client, operator_secret):
    _reset_totp_counter("000002")
    login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
    assert login.status_code == 200
    challenge = login.json()["challenge_token"]

    code = pyotp.TOTP(operator_secret).now()
    verified = client.post("/api/auth/mfa/verify", json={"challenge_token": challenge, "code": code})
    assert verified.status_code == 200, verified.text
    token = verified.json()["access_token"]

    response = client.get("/api/employees", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "perm.denied"


def test_admin_can_create_and_block_employee(client, admin_headers):
    tab_no = f"9{uuid.uuid4().int % 100000:05d}"
    created = client.post(
        "/api/employees",
        headers=admin_headers,
        json={"tab_no": tab_no, "full_name": "Тестов Тест Тестович", "role": "operator"},
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]

    duplicated = client.post(
        "/api/employees",
        headers=admin_headers,
        json={"tab_no": tab_no, "full_name": "Дубль Дубль Дубльевич", "role": "operator"},
    )
    assert duplicated.status_code == 409

    blocked = client.post(f"/api/employees/{employee_id}/block", headers=admin_headers)
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"

    login = client.post("/api/auth/login", json={"tab_no": tab_no, "password": "whatever"})
    assert login.status_code == 403
    assert login.json()["code"] == "auth.not_allowed"


def test_registration_requires_existing_employee(client):
    response = client.post("/api/auth/register/start", json={"tab_no": "888888"})
    assert response.status_code == 200
    body = response.json()
    # ответ нейтрален и не подтверждает наличие табельного
    assert body["next_step"] == "code_sent"
    assert body["debug_code"] is None


def test_registration_flow(client):
    tab_no = f"8{uuid.uuid4().int % 100000:05d}"
    admin = client.post("/api/auth/login", json={"tab_no": "000001", "password": "admin"})
    headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}

    created = client.post(
        "/api/employees",
        headers=headers,
        json={"tab_no": tab_no, "full_name": "Регистров Регистр Регистрович", "role": "operator"},
    )
    assert created.status_code == 201

    start = client.post("/api/auth/register/start", json={"tab_no": tab_no})
    code = start.json()["debug_code"]
    assert code

    verified = client.post("/api/auth/register/verify", json={"tab_no": tab_no, "code": code})
    assert verified.status_code == 200
    setup_token = verified.json()["setup_token"]

    weak = client.post(
        "/api/auth/register/complete", json={"setup_token": setup_token, "password": "123456"}
    )
    # короткий пароль отсекается либо схемой (422), либо политикой (400)
    assert weak.status_code in (400, 422)
    assert weak.json()["code"] == "validation.failed"

    done = client.post(
        "/api/auth/register/complete",
        json={"setup_token": setup_token, "password": "Obhodchik-2026"},
    )
    assert done.status_code == 200
    assert done.json()["user"]["tab_no"] == tab_no


def test_audit_is_written_and_immutable(client, admin_headers):
    response = client.get("/api/audit?limit=10", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    actions = {item["action"] for item in body["items"]}
    assert "auth.login.success" in actions

    from sqlalchemy import text
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        try:
            db.execute(text("update audit.audit_log set result='hacked' where id=(select max(id) from audit.audit_log)"))
            db.commit()
            raise AssertionError("журнал должен быть неизменяемым")
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001
            assert "append-only" in str(exc)
            db.rollback()
    finally:
        db.close()
