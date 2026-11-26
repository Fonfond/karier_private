"""Тесты Спринта 12: подложки карты, позиции портов в read-only графе, правка связей."""

from __future__ import annotations

import io
import uuid

from PIL import Image
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Link, MapLayer


def _png(width: int = 600, height: int = 400) -> bytes:
    image = Image.new("RGB", (width, height), (40, 60, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _asset(client, headers, type_code: str = "ktp") -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["type"]["code"] == type_code)


def test_map_layer_upload_activates_new_layer(client, admin_headers):
    db = SessionLocal()
    try:
        previous = db.scalar(
            select(MapLayer).where(MapLayer.is_active.is_(True)).order_by(MapLayer.version.desc())
        )
        previous_id = previous.id if previous else None
    finally:
        db.close()

    response = client.post(
        "/api/map/layers",
        headers=admin_headers,
        files={"file": ("map.png", _png(600, 400), "image/png")},
        data={"name": "Тестовая карта", "meters_per_pixel": "0.5", "origin_x": "0", "origin_y": "0"},
    )
    assert response.status_code == 201, response.text
    layer = response.json()
    assert layer["width_px"] == 600 and layer["height_px"] == 400
    assert layer["width_m"] == 300.0 and layer["height_m"] == 200.0

    active = client.get("/api/map/layers/active", headers=admin_headers).json()
    assert active["id"] == layer["id"]

    image = client.get(f"/api/map/layers/{layer['id']}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"

    # возвращаем прежнюю подложку, чтобы не менять демо
    db = SessionLocal()
    try:
        created = db.get(MapLayer, uuid.UUID(layer["id"]))
        if created is not None:
            db.delete(created)
        if previous_id is not None:
            old = db.get(MapLayer, previous_id)
            if old is not None:
                old.is_active = True
        db.commit()
    finally:
        db.close()


def test_map_layer_rejects_non_admin(client, admin_headers):
    from app.core.security import create_access_token
    from app.db.session import SessionLocal as Local
    from app.models import Employee, Role

    db = Local()
    try:
        role = db.scalar(select(Role).where(Role.code == "operator"))
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"M{uuid.uuid4().hex[:6].upper()}",
            full_name="Оператор Карты",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role="operator", session_id=str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/map/layers",
            headers=headers,
            files={"file": ("map.png", _png(), "image/png")},
            data={"name": "Нельзя", "meters_per_pixel": "0.5"},
        )
        assert response.status_code == 403

        db.delete(employee)
        db.commit()
    finally:
        db.close()


def test_graph_returns_saved_port_positions(client, admin_headers):
    """Read-only граф должен отдавать координаты портов, сохранённые админом."""
    asset = _asset(client, admin_headers, "bkru")
    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    node = next(item for item in graph["nodes"] if item["id"] == asset["id"])
    port = node["ports"][0]

    saved_x, saved_y = 0.31, 0.77
    response = client.put(
        "/api/topology/layout",
        headers=admin_headers,
        json={
            "items": [{"asset_id": asset["id"], "x": 320, "y": 240}],
            "ports": [{"port_id": port["id"], "x": saved_x, "y": saved_y}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated_ports"] == 1

    # дважды запрашиваем граф — как при переключении Карта → Схема → Карта → Схема
    for _ in range(2):
        fresh = client.get("/api/topology/graph", headers=admin_headers).json()
        node = next(item for item in fresh["nodes"] if item["id"] == asset["id"])
        saved = next(item for item in node["ports"] if item["id"] == port["id"])
        assert round(saved["schema_x"], 2) == saved_x
        assert round(saved["schema_y"], 2) == saved_y
        assert node["schema_x"] == 320.0
        assert node["schema_y"] == 240.0


def test_link_update_changes_graph_edge(client, admin_headers):
    links = client.get("/api/links", headers=admin_headers).json()["items"]
    assert links, "в демо-данных должны быть связи"
    link = links[0]

    response = client.patch(
        f"/api/links/{link['id']}",
        headers=admin_headers,
        json={"cable_mark": "АВБбШв 4×35", "length_m": 123.4, "state": "open"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["cable_mark"] == "АВБбШв 4×35"

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    edge = next(item for item in graph["edges"] if item["id"] == link["id"])
    assert edge["cable_mark"] == "АВБбШв 4×35"
    assert edge["length_m"] == 123.4
    assert edge["state"] == "open"

    db = SessionLocal()
    try:
        row = db.get(Link, uuid.UUID(link["id"]))
        row.cable_mark = link["cable_mark"]
        row.length_m = link["length_m"]
        row.state = link["state"]
        db.commit()
    finally:
        db.close()
