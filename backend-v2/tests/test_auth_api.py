"""API-тесты Спринта 1: вход, 2FA, роли, регистрация, аудит."""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import select, text, update

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
    # S-5: кода в ответе нет ни в каком виде
    assert "debug_code" not in body
    assert "code" not in body


def _admin_headers(client) -> dict:
    admin = client.post("/api/auth/login", json={"tab_no": "000001", "password": "admin"})
    assert admin.status_code == 200, admin.text
    return {"Authorization": f"Bearer {admin.json()['access_token']}"}


def _new_employee(client, headers: dict, tab_no: str) -> dict:
    created = client.post(
        "/api/employees",
        headers=headers,
        json={"tab_no": tab_no, "full_name": "Регистров Регистр Регистрович", "role": "operator"},
    )
    assert created.status_code == 201, created.text
    return created.json()


def _drop_employee(tab_no: str) -> None:
    db = SessionLocal()
    try:
        db.execute(text("delete from auth.employees where tab_no = :tab_no"), {"tab_no": tab_no})
        db.commit()
    finally:
        db.close()


def test_otp_issue_requires_admin(client, operator_secret):
    """Код выдаёт только администратор: аноним → 401, оператор → 403."""
    # для 401 достаточно любого id: зависимость проверяется до обработчика
    anonymous = client.post(f"/api/employees/{uuid.uuid4()}/otp")
    assert anonymous.status_code == 401, anonymous.text

    _reset_totp_counter("000002")
    login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
    assert login.status_code == 200, login.text
    body = login.json()
    verify = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": body["challenge_token"], "code": pyotp.TOTP(operator_secret).now()},
    )
    assert verify.status_code == 200, verify.text
    operator_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    forbidden = client.post(f"/api/employees/{uuid.uuid4()}/otp", headers=operator_headers)
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "perm.denied"


def test_registration_flow(client):
    # S-9: табельный вне демо-диапазона 8XXXXX и с уникальным суффиксом.
    # S-5: код выдаёт администратор через POST /employees/{id}/otp.
    tab_no = f"TST-{uuid.uuid4().hex[:8].upper()}"
    headers = _admin_headers(client)

    try:
        employee = _new_employee(client, headers, tab_no)

        start = client.post("/api/auth/register/start", json={"tab_no": tab_no})
        assert start.status_code == 200, start.text
        start_body = start.json()
        assert start_body["next_step"] == "code_required"
        assert start_body["expires_in"] == 0
        assert "debug_code" not in start_body and "code" not in start_body

        issued = client.post(f"/api/employees/{employee['id']}/otp", headers=headers)
        assert issued.status_code == 201, issued.text
        issued_body = issued.json()
        assert issued_body["expires_in"] == 600
        assert issued_body["tab_no"] == tab_no
        code = issued_body["code"]
        assert len(code) == 6 and code.isdigit()

        verified = client.post("/api/auth/register/verify", json={"tab_no": tab_no, "code": code})
        assert verified.status_code == 200, verified.text
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
    finally:
        # Сотрудник и его креды/сессии убираются за тестом (каскад в БД).
        _drop_employee(tab_no)


def test_otp_reissue_invalidates_previous(client):
    """Повторная выдача гасит прежний код: старый → 400, новый работает."""
    tab_no = f"TST-{uuid.uuid4().hex[:8].upper()}"
    headers = _admin_headers(client)
    try:
        employee = _new_employee(client, headers, tab_no)

        first = client.post(f"/api/employees/{employee['id']}/otp", headers=headers)
        assert first.status_code == 201, first.text
        old_code = first.json()["code"]

        second = client.post(f"/api/employees/{employee['id']}/otp", headers=headers)
        assert second.status_code == 201, second.text
        new_code = second.json()["code"]
        assert new_code != old_code

        stale = client.post("/api/auth/register/verify", json={"tab_no": tab_no, "code": old_code})
        assert stale.status_code == 400, stale.text
        # старый код больше не действует: активен только новый, поэтому API отвечает
        # либо «код неверный», либо «истёк» — оба варианта 400
        assert stale.json()["code"] in ("auth.code_invalid", "auth.code_expired")

        fresh = client.post("/api/auth/register/verify", json={"tab_no": tab_no, "code": new_code})
        assert fresh.status_code == 200, fresh.text
    finally:
        _drop_employee(tab_no)


def test_otp_used_and_expired_codes_rejected(client):
    """Использованный и истёкший коды дают 400 (S-5)."""
    tab_no = f"TST-{uuid.uuid4().hex[:8].upper()}"
    headers = _admin_headers(client)
    try:
        employee = _new_employee(client, headers, tab_no)

        used = client.post(f"/api/employees/{employee['id']}/otp", headers=headers).json()["code"]
        assert client.post(
            "/api/auth/register/verify", json={"tab_no": tab_no, "code": used}
        ).status_code == 200
        again = client.post("/api/auth/register/verify", json={"tab_no": tab_no, "code": used})
        assert again.status_code == 400, again.text
        assert again.json()["code"] == "auth.code_expired"

        expired = client.post(f"/api/employees/{employee['id']}/otp", headers=headers).json()["code"]
        db = SessionLocal()
        try:
            db.execute(
                text(
                    "update auth.onboarding_tokens set expires_at = now() - interval '1 minute' "
                    "where employee_id = (select id from auth.employees where tab_no = :tab_no) "
                    "and consumed_at is null"
                ),
                {"tab_no": tab_no},
            )
            db.commit()
        finally:
            db.close()

        late = client.post("/api/auth/register/verify", json={"tab_no": tab_no, "code": expired})
        assert late.status_code == 400, late.text
        assert late.json()["code"] == "auth.code_expired"
    finally:
        _drop_employee(tab_no)


def test_resend_invite_does_not_return_code(client):
    """Контракт S-5: resend-invite больше не отдаёт код, только факт выдачи."""
    tab_no = f"TST-{uuid.uuid4().hex[:8].upper()}"
    headers = _admin_headers(client)
    try:
        employee = _new_employee(client, headers, tab_no)

        empty = client.post(f"/api/employees/{employee['id']}/resend-invite", headers=headers)
        assert empty.status_code == 200, empty.text
        assert empty.json()["issued"] is False
        assert "debug_code" not in empty.json() and "code" not in empty.json()

        client.post(f"/api/employees/{employee['id']}/otp", headers=headers)
        issued = client.post(f"/api/employees/{employee['id']}/resend-invite", headers=headers)
        assert issued.status_code == 200, issued.text
        assert issued.json()["issued"] is True
        assert 0 < issued.json()["expires_in"] <= 600
        assert "debug_code" not in issued.json() and "code" not in issued.json()
    finally:
        _drop_employee(tab_no)


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
