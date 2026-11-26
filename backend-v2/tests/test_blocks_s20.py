"""Тесты Спринта 20: перемычки в payload блока."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset


def _instantiate(client, admin_headers, name="БКРУ перемычки в payload") -> dict:
    response = client.post(
        "/api/schema/blocks/bkru_standard/instantiate",
        headers=admin_headers,
        json={"x": 260, "y": 260, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_block_payload_contains_jumpers(client, admin_headers):
    data = _instantiate(client, admin_headers)
    db = SessionLocal()
    try:
        cells = [
            item
            for item in db.scalars(
                select(Asset).where(
                    Asset.schema_block_id == uuid.UUID(data["asset_id"]),
                    Asset.deleted_at.is_(None),
                )
            ).all()
            if item.schema_role == "outgoing"
        ]
        first, second = str(cells[0].id), str(cells[1].id)
    finally:
        db.close()

    created = client.post(
        f"/api/schema/assets/{data['asset_id']}/jumpers",
        headers=admin_headers,
        json={"from_cell_id": first, "to_cell_id": second, "label": "перемычка секций"},
    )
    assert created.status_code == 200, created.text

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    block = next(item for item in graph["blocks"] if item["asset_id"] == data["asset_id"])
    assert block["jumpers"], "перемычка должна попасть в payload блока"
    jumper = block["jumpers"][0]
    assert jumper["label"] == "перемычка секций"
    assert {jumper["from_cell_id"], jumper["to_cell_id"]} == {first, second}
