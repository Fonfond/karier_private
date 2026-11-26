"""Тесты Спринта 18: свёрнутый блок, перемычки, легенда, PDF с рамкой блока."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, Link


def _instantiate(client, admin_headers, code="bkru_standard", name="БКРУ С18") -> dict:
    response = client.post(
        f"/api/schema/blocks/{code}/instantiate",
        headers=admin_headers,
        json={"x": 200, "y": 200, "name": name},
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


def test_collapse_state_persisted(client, admin_headers):
    data = _instantiate(client, admin_headers, name="БКРУ сворачивание")

    collapsed = client.post(
        f"/api/schema/assets/{data['asset_id']}/collapse",
        headers=admin_headers,
        json={"collapsed": True},
    )
    assert collapsed.status_code == 200, collapsed.text
    assert collapsed.json()["collapsed"] is True

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    block = next(item for item in graph["blocks"] if item["asset_id"] == data["asset_id"])
    assert block["collapsed"] is True

    expanded = client.post(
        f"/api/schema/assets/{data['asset_id']}/collapse",
        headers=admin_headers,
        json={"collapsed": False},
    )
    assert expanded.json()["collapsed"] is False

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    block = next(item for item in graph["blocks"] if item["asset_id"] == data["asset_id"])
    assert block["collapsed"] is False


def test_jumper_inside_block(client, admin_headers):
    data = _instantiate(client, admin_headers, name="БКРУ перемычка")
    db = SessionLocal()
    try:
        cells = [item for item in _children(db, data["asset_id"]) if item.schema_role == "outgoing"]
        first, second = str(cells[0].id), str(cells[1].id)
    finally:
        db.close()

    response = client.post(
        f"/api/schema/assets/{data['asset_id']}/jumpers",
        headers=admin_headers,
        json={"from_cell_id": first, "to_cell_id": second, "label": "перемычка 1-2"},
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        jumpers = db.scalars(select(Link).where(Link.link_type == "jumper")).all()
        assert jumpers, "перемычка должна создать link с типом jumper"
    finally:
        db.close()


def test_jumper_between_blocks_rejected(client, admin_headers):
    left = _instantiate(client, admin_headers, name="БКРУ A")
    right = _instantiate(client, admin_headers, name="БКРУ B")

    db = SessionLocal()
    try:
        left_cell = _children(db, left["asset_id"])[0]
        right_cell = _children(db, right["asset_id"])[0]
        payload = {"from_cell_id": str(left_cell.id), "to_cell_id": str(right_cell.id)}
    finally:
        db.close()

    response = client.post(
        f"/api/schema/assets/{left['asset_id']}/jumpers", headers=admin_headers, json=payload
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "block.jumper_foreign"


def test_legend_lists_used_symbols(client, admin_headers):
    items = client.get("/api/schema/legend", headers=admin_headers).json()
    assert items
    symbols = {item["symbol"] for item in items}
    assert {"breaker", "busbar"} <= symbols
    breaker = next(item for item in items if item["symbol"] == "breaker")
    assert breaker["title"] == "Выключатель / ячейка"
    assert breaker["count"] >= 1


def test_pdf_contains_block_frame(client, admin_headers):
    data = _instantiate(client, admin_headers, name="ПС для PDF")
    response = client.get("/api/topology/schema.pdf", headers=admin_headers)
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 8000

    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        return

    reader = PdfReader(__import__("io").BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Условные обозначения" in text
    assert data["asset_id"] and "элементов" in text


def test_collapse_requires_admin(client, admin_headers):
    from app.core.security import create_access_token
    from app.models import Employee, Role

    data = _instantiate(client, admin_headers, name="БКРУ права")
    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.code == "operator"))
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"C{uuid.uuid4().hex[:6].upper()}",
            full_name="Оператор С18",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role="operator", session_id=str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            f"/api/schema/assets/{data['asset_id']}/collapse",
            headers=headers,
            json={"collapsed": True},
        )
        assert response.status_code == 403
        db.delete(employee)
        db.commit()
    finally:
        db.close()
