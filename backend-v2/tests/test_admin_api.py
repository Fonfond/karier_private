"""API-тесты Спринта 8: справочник, ручная раскладка схемы, учётные записи."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Asset, AssetType, Employee, Role


def _asset(client, headers, code: str) -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def _purge_types(codes: list[str]) -> None:
    """Убрать типы, созданные тестом (сначала потомков)."""
    db = SessionLocal()
    try:
        for code in reversed(codes):
            row = db.scalar(select(AssetType).where(AssetType.code == code))
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def _viewer_headers() -> tuple[dict, uuid.UUID]:
    """Токен сотрудника без прав администратора — для проверки 403."""
    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.code == "viewer"))
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"T{uuid.uuid4().hex[:6].upper()}",
            full_name="Наблюдатель Тестовый",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role="viewer", session_id=str(uuid.uuid4()))
        return {"Authorization": f"Bearer {token}"}, employee.id
    finally:
        db.close()


def _drop_viewer(employee_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        employee = db.get(Employee, employee_id)
        if employee is not None:
            db.delete(employee)
            db.commit()
    finally:
        db.close()


def test_type_tree_with_parent(client, admin_headers):
    parent_code = _unique("generator")
    child_code = _unique("gen_diesel")
    try:
        response = client.post(
            "/api/asset-types",
            headers=admin_headers,
            json={"code": parent_code, "name": "Генераторы", "category": "source", "icon": "⚡"},
        )
        assert response.status_code == 201, response.text
        parent = response.json()

        child = client.post(
            "/api/asset-types",
            headers=admin_headers,
            json={
                "code": child_code,
                "name": "Дизельные",
                "category": "source",
                "parent_id": parent["id"],
            },
        )
        assert child.status_code == 201, child.text
        assert child.json()["parent_id"] == parent["id"]
        assert child.json()["parent_name"] == "Генераторы"

        types = client.get("/api/asset-types", headers=admin_headers).json()
        by_code = {item["code"]: item for item in types}
        assert by_code[child_code]["parent_id"] == parent["id"]

        # вложить родителя в собственный подтип нельзя
        cycle = client.patch(
            f"/api/asset-types/{parent['id']}",
            headers=admin_headers,
            json={"parent_id": child.json()["id"]},
        )
        assert cycle.status_code == 400
        assert cycle.json()["code"] == "asset_type.parent_cycle"
    finally:
        _purge_types([parent_code, child_code])


def test_type_edit_and_deactivate(client, admin_headers):
    code = _unique("tmp_type")
    try:
        created = client.post(
            "/api/asset-types",
            headers=admin_headers,
            json={"code": code, "name": "Временный тип", "category": "aux"},
        ).json()

        updated = client.patch(
            f"/api/asset-types/{created['id']}",
            headers=admin_headers,
            json={
                "name": "Временный тип (изменён)",
                "icon": "🔧",
                "description": "Проверка редактирования",
                "port_template": {"ports": [{"code": "IN-1", "name": "Ввод", "kind": "in", "voltage_kv": 0.4}]},
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Временный тип (изменён)"
        assert updated.json()["port_template"]["ports"][0]["code"] == "IN-1"

        removed = client.delete(f"/api/asset-types/{created['id']}", headers=admin_headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["is_active"] is False

        active_codes = {item["code"] for item in client.get("/api/asset-types", headers=admin_headers).json()}
        assert code not in active_codes

        everything = client.get(
            "/api/asset-types?include_inactive=true", headers=admin_headers
        ).json()
        assert any(item["code"] == code and not item["is_active"] for item in everything)
    finally:
        _purge_types([code])


def test_type_in_use_cannot_be_deactivated(client, admin_headers):
    types = client.get("/api/asset-types", headers=admin_headers).json()
    ktp = next(item for item in types if item["code"] == "ktp")
    assert ktp["assets_count"] > 0

    response = client.delete(f"/api/asset-types/{ktp['id']}", headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["code"] == "asset_type.in_use"


def test_non_admin_cannot_manage_types_or_layout(client, admin_headers):
    headers, employee_id = _viewer_headers()
    try:
        denied_type = client.post(
            "/api/asset-types", headers=headers, json={"code": "hack_type", "name": "Нельзя"}
        )
        assert denied_type.status_code == 403

        asset = _asset(client, admin_headers, "KTP-14")
        denied_layout = client.put(
            "/api/topology/layout",
            headers=headers,
            json={"items": [{"asset_id": asset["id"], "x": 10, "y": 10}]},
        )
        assert denied_layout.status_code == 403
    finally:
        _drop_viewer(employee_id)


def test_asset_created_without_coordinates(client, admin_headers):
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "КТП без координат", "type_code": "ktp", "status": "off"},
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["x"] is None and asset["y"] is None
    assert asset["code"].startswith("KTP-")

    listed = client.get("/api/assets?limit=1000", headers=admin_headers).json()["items"]
    assert any(item["id"] == asset["id"] for item in listed)

    # убираем за собой
    assert client.delete(f"/api/assets/{asset['id']}", headers=admin_headers).status_code == 200


def test_schema_layout_saved_and_returned(client, admin_headers):
    first = _asset(client, admin_headers, "BKRU-1")
    second = _asset(client, admin_headers, "KTP-14")

    response = client.put(
        "/api/topology/layout",
        headers=admin_headers,
        json={
            "items": [
                {"asset_id": first["id"], "x": 120.5, "y": 80},
                {"asset_id": second["id"], "x": 420, "y": 260.25},
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes[first["id"]]["schema_x"] == 120.5
    assert nodes[first["id"]]["schema_y"] == 80.0
    assert nodes[second["id"]]["schema_x"] == 420.0

    # порты приходят в графе — по ним схема соединяет узлы
    assert nodes[first["id"]]["ports"], "у узла должны быть порты для ручного соединения"


def test_schema_layout_ignores_unknown_assets(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    response = client.put(
        "/api/topology/layout",
        headers=admin_headers,
        json={
            "items": [
                {"asset_id": asset["id"], "x": 10, "y": 20},
                {"asset_id": str(uuid.uuid4()), "x": 30, "y": 40},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert len(response.json()["skipped"]) == 1


def test_asset_soft_delete_hides_from_registry(client, admin_headers):
    created = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "Временный объект", "type_code": "ktp"},
    ).json()

    deleted = client.delete(f"/api/assets/{created['id']}", headers=admin_headers)
    assert deleted.status_code == 200

    items = client.get("/api/assets?limit=1000", headers=admin_headers).json()["items"]
    assert all(item["id"] != created["id"] for item in items)

    db = SessionLocal()
    try:
        row = db.get(Asset, uuid.UUID(created["id"]))
        assert row is not None and row.deleted_at is not None
    finally:
        db.close()


def test_employee_edit_and_dismiss(client, admin_headers):
    created = client.post(
        "/api/employees",
        headers=admin_headers,
        json={
            "tab_no": f"T{uuid.uuid4().hex[:5].upper()}",
            "full_name": "Проверкин Пётр Петрович",
            "position": "Электромонтёр",
            "role": "operator",
        },
    )
    assert created.status_code == 201, created.text
    employee = created.json()

    updated = client.patch(
        f"/api/employees/{employee['id']}",
        headers=admin_headers,
        json={"full_name": "Проверкин Пётр Иванович", "position": "Старший электромонтёр", "role": "viewer"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Проверкин Пётр Иванович"
    assert updated.json()["position"] == "Старший электромонтёр"
    assert updated.json()["role"] == "viewer"

    dismissed = client.delete(f"/api/employees/{employee['id']}", headers=admin_headers)
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"

    db = SessionLocal()
    try:
        row = db.get(Employee, uuid.UUID(employee["id"]))
        assert row is not None
        assert row.status == "dismissed"
        db.delete(row)
        db.commit()
    finally:
        db.close()


def test_admin_cannot_dismiss_self(client, admin_headers):
    me = client.get("/api/me", headers=admin_headers).json()
    response = client.delete(f"/api/employees/{me['id']}", headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["code"] == "employee.self_action"


def test_tree_codes_unique(client, admin_headers):
    db = SessionLocal()
    try:
        codes = db.scalars(select(AssetType.code)).all()
        assert len(codes) == len(set(codes))
    finally:
        db.close()
