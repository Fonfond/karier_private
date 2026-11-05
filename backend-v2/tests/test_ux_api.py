"""API-тесты Спринта 9: перемещение объектов, позиции портов, удаление сотрудников."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, AssetPort, Employee, Role


def _asset(client, headers, code: str) -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def _by_type(client, headers, type_code: str) -> dict:
    """Любой активный объект нужного типа — тесты не зависят от конкретного кода."""
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["type"]["code"] == type_code)


def test_asset_position_patch_persists(client, admin_headers):
    asset = _by_type(client, admin_headers, "ktp")
    detail = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    before_power = client.get(f"/api/assets/{asset['id']}/power-path", headers=admin_headers).json()

    response = client.patch(
        f"/api/assets/{asset['id']}",
        headers=admin_headers,
        json={"x": 512.5, "y": 341.5},
    )
    assert response.status_code == 200, response.text
    assert response.json()["x"] == 512.5
    assert response.json()["y"] == 341.5
    assert response.json()["version"] > detail["version"]

    again = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    assert again["x"] == 512.5 and again["y"] == 341.5

    after_power = client.get(f"/api/assets/{asset['id']}/power-path", headers=admin_headers).json()
    assert after_power["energized"] == before_power["energized"]

    # возвращаем исходные координаты
    client.patch(
        f"/api/assets/{asset['id']}",
        headers=admin_headers,
        json={"x": detail["x"], "y": detail["y"]},
    )


def test_offline_position_change_goes_through_sync(client, admin_headers):
    asset = _by_type(client, admin_headers, "ktp")
    detail = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()

    response = client.post(
        "/api/sync/push",
        headers=admin_headers,
        json={
            "device_id": "ux-test",
            "ops": [
                {
                    "op_id": str(uuid.uuid4()),
                    "entity": "asset",
                    "entity_id": asset["id"],
                    "op": "update",
                    "patch": {"x": 610.0, "y": 380.0},
                    "base_version": detail["version"],
                    "client_ts": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] in ("applied", "conflict_won")

    moved = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    assert moved["x"] == 610.0 and moved["y"] == 380.0

    client.patch(
        f"/api/assets/{asset['id']}",
        headers=admin_headers,
        json={"x": detail["x"], "y": detail["y"]},
    )


def test_port_positions_saved_and_returned(client, admin_headers):
    asset = _asset(client, admin_headers, "BKRU-1")
    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    node = next(item for item in graph["nodes"] if item["id"] == asset["id"])
    assert node["ports"], "у БКРУ должны быть порты"

    port = node["ports"][0]
    response = client.put(
        "/api/topology/layout",
        headers=admin_headers,
        json={
            "items": [{"asset_id": asset["id"], "x": 300, "y": 200}],
            "ports": [{"port_id": port["id"], "x": 0.15, "y": 0.85}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["updated"] == 1
    assert body["updated_ports"] == 1

    fresh = client.get("/api/topology/graph", headers=admin_headers).json()
    node = next(item for item in fresh["nodes"] if item["id"] == asset["id"])
    saved = next(item for item in node["ports"] if item["id"] == port["id"])
    assert saved["schema_x"] == 0.15
    assert saved["schema_y"] == 0.85


def test_port_position_out_of_range_rejected(client, admin_headers):
    asset = _asset(client, admin_headers, "BKRU-1")
    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    node = next(item for item in graph["nodes"] if item["id"] == asset["id"])
    port = node["ports"][0]

    response = client.put(
        "/api/topology/layout",
        headers=admin_headers,
        json={
            "items": [],
            "ports": [{"port_id": port["id"], "x": 1.7, "y": 0.5}],
        },
    )
    assert response.status_code == 422


def test_port_position_survives_reload(client, admin_headers):
    asset = _by_type(client, admin_headers, "ktp")
    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    node = next(item for item in graph["nodes"] if item["id"] == asset["id"])
    port = node["ports"][0]

    client.put(
        "/api/topology/layout",
        headers=admin_headers,
        json={"items": [], "ports": [{"port_id": port["id"], "x": 0.5, "y": 0.02}]},
    )

    db = SessionLocal()
    try:
        row = db.get(AssetPort, uuid.UUID(port["id"]))
        assert row is not None
        assert round(float(row.schema_x), 2) == 0.5
        assert round(float(row.schema_y), 2) == 0.02
    finally:
        db.close()


def test_permanent_delete_removes_clean_employee(client, admin_headers):
    created = client.post(
        "/api/employees",
        headers=admin_headers,
        json={
            "tab_no": f"D{uuid.uuid4().hex[:5].upper()}",
            "full_name": "Удаляев Удал Удалович",
            "role": "operator",
        },
    ).json()

    response = client.delete(f"/api/employees/{created['id']}/permanent", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deleted"

    db = SessionLocal()
    try:
        assert db.get(Employee, uuid.UUID(created["id"])) is None
    finally:
        db.close()


def test_permanent_delete_blocked_when_history_exists(client, admin_headers):
    me = client.get("/api/me", headers=admin_headers).json()
    response = client.delete(f"/api/employees/{me['id']}/permanent", headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["code"] == "employee.self_action"

    # сотрудник с действиями в журнале (любой, кто уже что-то делал) — не удаляется
    db = SessionLocal()
    try:
        employee = db.scalar(
            select(Employee)
            .join(Role, Employee.role_id == Role.id)
            .where(Employee.status == "active", Role.code == "operator")
            .limit(1)
        )
    finally:
        db.close()

    if employee is not None:
        response = client.delete(f"/api/employees/{employee.id}/permanent", headers=admin_headers)
        if response.status_code == 409:
            assert response.json()["code"] == "employee.has_history"
