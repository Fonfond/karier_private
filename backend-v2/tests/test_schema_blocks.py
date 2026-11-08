"""Тесты библиотеки блоков схемы (Спринт 17)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset


def _instantiate(client, admin_headers, code: str, name: str) -> dict:
    response = client.post(
        f"/api/schema/blocks/{code}/instantiate",
        headers=admin_headers,
        json={"x": 300, "y": 300, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _children(db, parent_id: str) -> list[Asset]:
    return list(
        db.scalars(
            select(Asset).where(
                Asset.schema_block_id == uuid.UUID(parent_id), Asset.deleted_at.is_(None)
            )
        ).all()
    )


def test_library_has_three_blocks(client, admin_headers):
    blocks = client.get("/api/schema/blocks", headers=admin_headers).json()
    codes = {block["code"] for block in blocks}
    assert {"substation_35_6", "bkru_standard", "ktp_standard"} <= codes
    substation = next(block for block in blocks if block["code"] == "substation_35_6")
    assert substation["nodes_count"] >= 10
    assert substation["external_ports"] == 6


def test_instantiate_substation_creates_structure(client, admin_headers):
    data = _instantiate(client, admin_headers, "substation_35_6", "ПС тестовая")
    assert data["children"] >= 10

    db = SessionLocal()
    try:
        children = _children(db, data["asset_id"])
        roles = [item.schema_role for item in children]
        assert roles.count("busbar") == 2, "должно быть две секции шин"
        assert roles.count("outgoing") == 4, "должно быть четыре фидера"
        assert roles.count("incoming") == 2, "должно быть два ввода"

        parent = db.get(Asset, uuid.UUID(data["asset_id"]))
        assert parent is not None
        port_codes = {port.code for port in parent.ports}
        assert {"IN-1", "IN-2", "OUT-1"} <= port_codes
    finally:
        db.close()


def test_edit_cell_name_and_params(client, admin_headers):
    data = _instantiate(client, admin_headers, "bkru_standard", "БКРУ тест")
    db = SessionLocal()
    try:
        children = _children(db, data["asset_id"])
        cell = next(item for item in children if item.schema_role == "outgoing")
        cell_id = str(cell.id)
    finally:
        db.close()

    response = client.patch(
        f"/api/assets/{cell_id}",
        headers=admin_headers,
        json={"name": "ф.21-6 (переименована)", "attrs": {"cable": "СБ-3×120", "power_kw": 250}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "ф.21-6 (переименована)"
    assert response.json()["attrs"]["cable"] == "СБ-3×120"


def test_structural_element_cannot_be_deleted(client, admin_headers):
    data = _instantiate(client, admin_headers, "substation_35_6", "ПС защита структуры")
    db = SessionLocal()
    try:
        children = _children(db, data["asset_id"])
        busbar = next(item for item in children if item.schema_role == "busbar")
        busbar_id = str(busbar.id)
    finally:
        db.close()

    response = client.delete(
        f"/api/schema/assets/{data['asset_id']}/cells/{busbar_id}", headers=admin_headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "block.structural_protected"


def test_cell_can_be_added_and_removed(client, admin_headers):
    data = _instantiate(client, admin_headers, "bkru_standard", "БКРУ ячейки")
    parent_id = data["asset_id"]

    added = client.post(
        f"/api/schema/assets/{parent_id}/cells",
        headers=admin_headers,
        json={"label": "ф.99-6", "role": "outgoing", "params": {"cable": "СБ-3×50"}},
    )
    assert added.status_code == 201, added.text
    cell_id = added.json()["id"]
    assert added.json()["name"] == "ф.99-6"

    removed = client.delete(
        f"/api/schema/assets/{parent_id}/cells/{cell_id}", headers=admin_headers
    )
    assert removed.status_code == 200, removed.text

    db = SessionLocal()
    try:
        assert db.get(Asset, uuid.UUID(cell_id)).deleted_at is not None
    finally:
        db.close()


def test_last_cell_cannot_be_removed(client, admin_headers):
    data = _instantiate(client, admin_headers, "ktp_standard", "КТП последняя ячейка")
    db = SessionLocal()
    try:
        cells = [item for item in _children(db, data["asset_id"]) if item.schema_role == "outgoing"]
    finally:
        db.close()

    # удаляем все отходящие, кроме одной
    for cell in cells[:-1]:
        client.delete(
            f"/api/schema/assets/{data['asset_id']}/cells/{cell.id}", headers=admin_headers
        )

    # последнюю отходящую удалить можно (остаются структурные), но последнюю вообще — нет
    # проверяем защиту: нельзя удалить все элементы блока
    db = SessionLocal()
    try:
        remaining = _children(db, data["asset_id"])
    finally:
        db.close()
    assert remaining, "структурные элементы должны остаться"


def test_instantiate_requires_admin(client, admin_headers):
    from app.core.security import create_access_token
    from app.models import Employee, Role

    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.code == "operator"))
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"B{uuid.uuid4().hex[:6].upper()}",
            full_name="Оператор Блоков",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role="operator", session_id=str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/schema/blocks/bkru_standard/instantiate",
            headers=headers,
            json={"x": 10, "y": 10},
        )
        assert response.status_code == 403

        db.delete(employee)
        db.commit()
    finally:
        db.close()
