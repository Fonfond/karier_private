"""Тесты Спринта 22: топология v2 по эскизу и ПУЭ."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset

JSON_PATH = Path(__file__).resolve().parents[1] / "seed_data" / "sketch_v2.json"


def test_bkru_has_two_sections_and_two_inputs(client, admin_headers):
    response = client.post(
        "/api/schema/blocks/bkru_standard/instantiate",
        headers=admin_headers,
        json={"x": 100, "y": 100, "name": "БКРУ-1 проверка"},
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
        sections = [item for item in children if item.schema_role == "busbar"]
        incoming = [item for item in children if item.schema_role == "incoming"]
        feeders = [item for item in children if item.schema_role == "outgoing"]
        assert len(sections) == 2, "БКРУ должно иметь две секции шин"
        assert len(incoming) == 2, "БКРУ должно иметь два ввода"
        assert {item.name for item in feeders} == {"ф.2 · QF+ТТ (яч. 4)", "ф.3 · QF+ТТ (яч. 5)", "ф.5 · QF+ТТ (яч. 6)"}

        parent = db.get(Asset, uuid.UUID(data["asset_id"]))
        assert {port.code for port in parent.ports} == {"IN-1", "IN-2", "OUT-1", "OUT-2", "OUT-3"}
    finally:
        db.close()


def test_yakno6_has_cells_and_loads(client, admin_headers):
    response = client.post(
        "/api/schema/blocks/yakno6/instantiate",
        headers=admin_headers,
        json={"x": 120, "y": 120, "name": "ЯКНО-6 проверка"},
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
        cells = [item for item in children if item.schema_role == "outgoing"]
        loads = [item for item in children if item.schema_role == "load"]
        assert len(cells) == 6, "ЯКНО-6 — шесть ячеек"
        assert len(loads) == 3, "к ЯКНО-6 подключены три ЭКГ"
        assert any("ЭКГ-15М" in item.name for item in loads)
        assert all((item.attrs or {}).get("power_kw") for item in loads)
    finally:
        db.close()


def test_ps_has_qf_tt_meter_on_feeders(client, admin_headers):
    response = client.post(
        "/api/schema/blocks/substation_35_6/instantiate",
        headers=admin_headers,
        json={"x": 80, "y": 80, "name": "ПС проверка"},
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
        feeders = [item for item in children if item.schema_role == "outgoing"]
        assert len(feeders) == 3
        for feeder in feeders:
            attrs = feeder.attrs or {}
            assert attrs.get("qf"), f"у {feeder.name} нет QF"
            assert attrs.get("ct"), f"у {feeder.name} нет ТТ"
            assert attrs.get("meter") == "Wh", f"у {feeder.name} нет учёта"
            assert attrs.get("opn"), f"у {feeder.name} нет ОПН"
    finally:
        db.close()


def test_sketch_json_v2_matches_sketch():
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == "2.0"
    assert payload["dangling_ports"] == []

    blocks = {block["id"]: block for block in payload["blocks"]}
    by_code = {}
    for block in payload["blocks"]:
        by_code.setdefault(block["block"], []).append(block)

    ps = by_code["substation_35_6"][0]
    ps_feeders = {item["name"] for item in ps["params"]["feeders"]}
    assert ps_feeders == {"ф.7к · QF VD4 630A · ТТ 600/5 0.5S · Wh (яч. 5)",
                         "ф.16к · QF VD4 630A · ТТ 600/5 · Wh (яч. 9)",
                         "ф.21к · QF VD4 630A · ТТ 600/5 · Wh (яч. 12)"}

    bkru = by_code["bkru_standard"][0]
    assert len(bkru["params"]["sections"]) == 2
    assert len(bkru["params"]["incoming"]) == 2

    links = payload["links"]
    assert any(link["type"] == "overhead" for link in links), "ВЛ должны быть overhead"

    def linked(titles: tuple[str, str]) -> bool:
        for link in links:
            a = blocks[link["from"]["block"]]["title"]
            b = blocks[link["to"]["block"]]["title"]
            if {a, b} == set(titles):
                return True
        return False

    assert linked(("ПС 35/6 кВ «Карьер»", "ЯКНО-6")), "ф.16к должен идти на ЯКНО-6"
    assert linked(("ПС 35/6 кВ «Карьер»", "БКРУ-1")), "ф.21к должен идти на БКРУ-1"
    assert linked(("ЯКНО-1/1к", "БКРУ-1")), "ЯКНО-1/1к питает ввод 2 БКРУ-1"
    assert linked(("оп.4", "ЯКНО-1/1к")), "отпайка на ЯКНО-1/1к — с оп.4"
