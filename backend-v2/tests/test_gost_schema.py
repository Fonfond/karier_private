"""Тесты Спринта 16: ГОСТ-символы, рамка листа, PDF схемы."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, Employee, Role


def test_graph_nodes_have_schema_symbols(client, admin_headers):
    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    assert graph["nodes"]
    symbols = {node["schema_symbol"] for node in graph["nodes"]}
    assert "busbar" in symbols or "breaker" in symbols
    assert all(node["schema_symbol"] for node in graph["nodes"])

    bus = next((node for node in graph["nodes"] if node["schema_symbol"] == "busbar"), None)
    assert bus is not None, "секции шин должны иметь символ busbar"


def test_type_symbol_editable(client, admin_headers):
    types = client.get("/api/asset-types", headers=admin_headers).json()
    ktp = next(item for item in types if item["code"] == "ktp")
    original = ktp["schema_symbol"]

    response = client.patch(
        f"/api/asset-types/{ktp['id']}", headers=admin_headers, json={"schema_symbol": "disconnector"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["schema_symbol"] == "disconnector"

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    asset = client.get("/api/assets?limit=1000", headers=admin_headers).json()["items"]
    ktp_asset = next(item for item in asset if item["type"]["code"] == "ktp")
    node = next(item for item in graph["nodes"] if item["id"] == ktp_asset["id"])
    assert node["schema_symbol"] == "disconnector"

    client.patch(
        f"/api/asset-types/{ktp['id']}", headers=admin_headers, json={"schema_symbol": original}
    )


def test_frame_defaults_and_update(client, admin_headers):
    frame = client.get("/api/topology/frame", headers=admin_headers).json()
    assert frame["sheet_format"] == "A3"
    assert frame["organization"]

    updated = client.put(
        "/api/topology/frame",
        headers=admin_headers,
        json={
            "sheet_format": "A3",
            "organization": "ООО «Удоканская медь»",
            "department": "Служба главного энергетика",
            "object_name": "Однолинейная схема 6 кВ, БКРУ-1",
            "sheet": "Лист 1",
            "scale": "б/м",
            "developed_by": "Инженер-электрик",
            "checked_by": "Главный энергетик",
            "approved_by": "Главный инженер",
            "date": "08.11.2026",
            "show_on_screen": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["object_name"] == "Однолинейная схема 6 кВ, БКРУ-1"

    again = client.get("/api/topology/frame", headers=admin_headers).json()
    assert again["approved_by"] == "Главный инженер"

    # вернуть исходное название
    client.put(
        "/api/topology/frame",
        headers=admin_headers,
        json={**frame, "show_on_screen": True},
    )


def test_frame_requires_admin(client, admin_headers):
    from app.core.security import create_access_token

    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.code == "operator"))
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"F{uuid.uuid4().hex[:6].upper()}",
            full_name="Оператор Штампа",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role="operator", session_id=str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {token}"}

        response = client.put(
            "/api/topology/frame", headers=headers, json={"object_name": "Нельзя"}
        )
        assert response.status_code == 403

        db.delete(employee)
        db.commit()
    finally:
        db.close()


def test_schema_pdf_renders(client, admin_headers):
    response = client.get("/api/topology/schema.pdf", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 5000


def test_symbols_cover_known_types(client, admin_headers):
    types = client.get("/api/asset-types", headers=admin_headers).json()
    allowed = {
        "breaker",
        "disconnector",
        "busbar",
        "load",
        "generator",
        "source",
        "line",
        "ct",
        "arrester",
    }
    assert all(item.get("schema_symbol") in allowed for item in types)


def test_assets_present_for_schema(client, admin_headers):
    db = SessionLocal()
    try:
        count = len(
            [
                asset
                for asset in db.scalars(select(Asset)).all()
                if asset.deleted_at is None
            ]
        )
    finally:
        db.close()
    assert count >= 20
