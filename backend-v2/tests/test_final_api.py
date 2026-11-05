"""API-тесты финального спринта: удаление дефектов и презентационные данные."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Defect


def _asset(client, headers, type_code: str = "ktp") -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["type"]["code"] == type_code)


def test_defect_soft_delete_hides_from_list_and_dashboard(client, admin_headers):
    asset = _asset(client, admin_headers)
    before = client.get("/api/dashboard/summary", headers=admin_headers).json()["defects"]["open"]

    created = client.post(
        "/api/defects",
        headers=admin_headers,
        json={
            "asset_id": asset["id"],
            "severity": "low",
            "description": "Тестовый дефект для удаления",
        },
    )
    assert created.status_code == 201, created.text
    defect_id = created.json()["id"]

    listed = client.get("/api/defects", headers=admin_headers).json()["items"]
    assert any(item["id"] == defect_id for item in listed)

    after_create = client.get("/api/dashboard/summary", headers=admin_headers).json()["defects"]["open"]
    assert after_create == before + 1

    removed = client.delete(f"/api/defects/{defect_id}", headers=admin_headers)
    assert removed.status_code == 200, removed.text

    listed_after = client.get("/api/defects", headers=admin_headers).json()["items"]
    assert all(item["id"] != defect_id for item in listed_after)

    after_delete = client.get("/api/dashboard/summary", headers=admin_headers).json()["defects"]["open"]
    assert after_delete == before

    db = SessionLocal()
    try:
        row = db.get(Defect, uuid.UUID(defect_id))
        assert row is not None and row.deleted_at is not None, "дефект должен остаться в БД"
    finally:
        db.close()


def test_deleted_defect_cannot_be_updated(client, admin_headers):
    asset = _asset(client, admin_headers)
    created = client.post(
        "/api/defects",
        headers=admin_headers,
        json={"asset_id": asset["id"], "severity": "low", "description": "Удаляемый дефект"},
    ).json()

    client.delete(f"/api/defects/{created['id']}", headers=admin_headers)
    response = client.patch(
        f"/api/defects/{created['id']}", headers=admin_headers, json={"status": "fixed"}
    )
    assert response.status_code == 404


def test_defect_delete_requires_admin(client, admin_headers):
    asset = _asset(client, admin_headers)
    created = client.post(
        "/api/defects",
        headers=admin_headers,
        json={"asset_id": asset["id"], "severity": "low", "description": "Дефект для проверки прав"},
    ).json()

    from app.core.security import create_access_token
    from app.db.session import SessionLocal as Local
    from app.models import Employee, Role

    db = Local()
    try:
        role = db.scalar(select(Role).where(Role.code == "operator"))
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"P{uuid.uuid4().hex[:6].upper()}",
            full_name="Оператор Проверочный",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role="operator", session_id=str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {token}"}

        denied = client.delete(f"/api/defects/{created['id']}", headers=headers)
        assert denied.status_code == 403

        db.delete(employee)
        db.commit()
    finally:
        db.close()

    client.delete(f"/api/defects/{created['id']}", headers=admin_headers)
