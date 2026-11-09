"""Тесты Спринта 21: шаблон ПС по эскизу и простые блоки (опора, реклоузер)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset


def test_substation_template_matches_sketch(client, admin_headers):
    response = client.post(
        "/api/schema/blocks/substation_35_6/instantiate",
        headers=admin_headers,
        json={"x": 60, "y": 60, "name": "ПС по эскизу"},
    )
    assert response.status_code == 201, response.text
    data = response.json()

    db = SessionLocal()
    try:
        children = db.scalars(
            select(Asset).where(
                Asset.schema_block_id == uuid.UUID(data["asset_id"]),
                Asset.deleted_at.is_(None),
            )
        ).all()
        busbars = [item for item in children if item.schema_role == "busbar"]
        names = {item.name for item in children}

        assert len(busbars) == 2
        assert any("I секция шин" in item.name for item in busbars)
        assert any("II секция шин" in item.name for item in busbars)
        assert {"ф.7к", "ф.16к", "ф.21к", "ф.5к"} <= names
        assert any("СВ" in item.name for item in children if item.schema_role == "section")
        assert any("Ввод 1" in item.name for item in children if item.schema_role == "incoming")
        assert any("Ввод 2" in item.name for item in children if item.schema_role == "incoming")
    finally:
        db.close()


def test_simple_blocks_available(client, admin_headers):
    blocks = client.get("/api/schema/blocks", headers=admin_headers).json()
    by_code = {block["code"]: block for block in blocks}
    assert {"pole", "recloser", "yakno", "rlnd"} <= set(by_code)
    assert by_code["pole"]["block_type"] == "simple"
    assert by_code["recloser"]["block_type"] == "simple"


def test_pole_instantiate_with_number(client, admin_headers):
    response = client.post(
        "/api/schema/blocks/pole/instantiate",
        headers=admin_headers,
        json={"x": 200, "y": 200, "name": "оп.14"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["children"] == 0

    db = SessionLocal()
    try:
        pole = db.get(Asset, uuid.UUID(data["asset_id"]))
        assert pole is not None
        assert pole.name == "оп.14"
        assert (pole.attrs or {}).get("pole_no") == "оп.14"
        codes = {port.code for port in pole.ports}
        assert {"IN-1", "OUT-1"} <= codes
    finally:
        db.close()
