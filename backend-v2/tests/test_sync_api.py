"""API-тесты Спринта 5: журнал изменений, push/pull, конфликты, перемещения."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Asset, AssetMove, ChangeLog, Conflict, SyncOp


def _asset(client, headers, code: str) -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def _db():
    return SessionLocal()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_change_log_written_by_trigger(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")

    db = _db()
    try:
        before = db.scalar(select(func.max(ChangeLog.seq))) or 0
    finally:
        db.close()

    response = client.post(
        f"/api/assets/{asset['id']}/state",
        headers=admin_headers,
        json={"status": "off", "reason": "проверка журнала"},
    )
    assert response.status_code == 200

    db = _db()
    try:
        rows = db.scalars(
            select(ChangeLog).where(ChangeLog.seq > before, ChangeLog.entity == "asset")
        ).all()
        assert rows, "триггер должен записать изменение объекта в журнал"
        assert any(row.entity_id == uuid.UUID(asset["id"]) for row in rows)
    finally:
        db.close()

    client.post(
        f"/api/assets/{asset['id']}/state",
        headers=admin_headers,
        json={"status": "on", "reason": "проверка завершена"},
    )


def test_push_idempotency(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-15")
    op_id = str(uuid.uuid4())
    payload = {
        "device_id": "test-device",
        "ops": [
            {
                "op_id": op_id,
                "entity": "asset",
                "entity_id": asset["id"],
                "op": "update",
                "patch": {"status": "on"},
                "base_version": asset["version"],
                "client_ts": _now().isoformat(),
            }
        ],
    }

    first = client.post("/api/sync/push", headers=admin_headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["results"][0]["status"] in ("applied", "conflict_won")

    second = client.post("/api/sync/push", headers=admin_headers, json=payload)
    assert second.status_code == 200
    assert second.json()["results"][0]["status"] == "duplicate"

    db = _db()
    try:
        assert db.get(SyncOp, uuid.UUID(op_id)) is not None
    finally:
        db.close()


def test_push_conflict_lost_keeps_server_value(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    detail = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()

    # меняем на сервере позже, чем «клиентское» время
    stale_ts = (_now() - timedelta(hours=2)).isoformat()
    response = client.post(
        "/api/sync/push",
        headers=admin_headers,
        json={
            "device_id": "test-device",
            "ops": [
                {
                    "op_id": str(uuid.uuid4()),
                    "entity": "asset",
                    "entity_id": asset["id"],
                    "op": "update",
                    "patch": {"status": "off"},
                    "base_version": detail["version"] - 1,
                    "client_ts": stale_ts,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "conflict_lost"
    assert result["conflict_id"]

    after = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    assert after["status"] == detail["status"], "старое изменение не должно применяться"

    conflicts = client.get("/api/sync/conflicts", headers=admin_headers).json()
    assert conflicts["total"] >= 1
    assert any(item["winner"] == "server" for item in conflicts["items"])


def test_push_conflict_won_applies_and_records(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    detail = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()

    future_ts = (_now() + timedelta(hours=1)).isoformat()
    response = client.post(
        "/api/sync/push",
        headers=admin_headers,
        json={
            "device_id": "test-device",
            "ops": [
                {
                    "op_id": str(uuid.uuid4()),
                    "entity": "asset",
                    "entity_id": asset["id"],
                    "op": "update",
                    "patch": {"status": "maintenance"},
                    "base_version": detail["version"] - 1,
                    "client_ts": future_ts,
                }
            ],
        },
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "conflict_won"

    after = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    assert after["status"] == "maintenance"

    client.post(
        f"/api/assets/{asset['id']}/state",
        headers=admin_headers,
        json={"status": "on", "reason": "восстановление после теста"},
    )


def test_offline_move_keeps_power_graph(client, admin_headers):
    asset = _asset(client, admin_headers, "DMO-1")
    before = client.get(f"/api/assets/{asset['id']}/power-path", headers=admin_headers).json()

    response = client.post(
        "/api/sync/push",
        headers=admin_headers,
        json={
            "device_id": "test-device",
            "ops": [
                {
                    "op_id": str(uuid.uuid4()),
                    "entity": "move",
                    "entity_id": asset["id"],
                    "op": "update",
                    "patch": {"x": 640.0, "y": 480.0, "note": "переставили на гор. +85"},
                    "client_ts": (_now() + timedelta(minutes=5)).isoformat(),
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "applied"

    moved = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    assert moved["x"] == 640.0 and moved["y"] == 480.0

    after = client.get(f"/api/assets/{asset['id']}/power-path", headers=admin_headers).json()
    assert after["energized"] == before["energized"]
    assert [node["code"] for node in after["chain"]] == [node["code"] for node in before["chain"]]

    moves = client.get(f"/api/assets/{asset['id']}/moves", headers=admin_headers).json()
    assert moves["total"] >= 1
    assert moves["items"][0]["note"] == "переставили на гор. +85"


def test_move_race_keeps_both_moves(client, admin_headers):
    asset = _asset(client, admin_headers, "DMO-1")

    # «позднее» перемещение от другого устройства
    client.post(
        f"/api/assets/{asset['id']}/move",
        headers=admin_headers,
        json={"x": 700.0, "y": 500.0, "note": "перемещение с сервера"},
    )

    stale = (_now() - timedelta(hours=3)).isoformat()
    response = client.post(
        "/api/sync/push",
        headers=admin_headers,
        json={
            "device_id": "test-device",
            "ops": [
                {
                    "op_id": str(uuid.uuid4()),
                    "entity": "move",
                    "entity_id": asset["id"],
                    "op": "update",
                    "patch": {"x": 100.0, "y": 100.0, "note": "старое офлайн-перемещение"},
                    "client_ts": stale,
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "conflict_lost"

    current = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
    assert current["x"] == 700.0 and current["y"] == 500.0

    moves = client.get(f"/api/assets/{asset['id']}/moves", headers=admin_headers).json()
    notes = [item["note"] for item in moves["items"]]
    assert "старое офлайн-перемещение" in notes, "проигравшее перемещение должно остаться в истории"
    assert any(item["conflict"] for item in moves["items"])


def test_move_endpoint_rejects_stationary_asset(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    response = client.post(
        f"/api/assets/{asset['id']}/move",
        headers=admin_headers,
        json={"x": 10, "y": 10, "note": "нельзя"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "move.not_mobile"


def test_pull_returns_delta(client, admin_headers):
    state = client.get("/api/sync/state", headers=admin_headers).json()
    since = state["last_seq"]

    asset = _asset(client, admin_headers, "KTP-15")
    client.post(
        f"/api/assets/{asset['id']}/state",
        headers=admin_headers,
        json={"status": "off", "reason": "проверка pull"},
    )

    pull = client.get(f"/api/sync/pull?since={since}", headers=admin_headers)
    assert pull.status_code == 200
    body = pull.json()
    assert body["changes"], "должны прийти изменения после указанного seq"
    assert body["last_seq"] > since
    assert all(change["seq"] > since for change in body["changes"])

    empty = client.get(f"/api/sync/pull?since={body['last_seq']}", headers=admin_headers).json()
    assert empty["changes"] == []

    client.post(
        f"/api/assets/{asset['id']}/state",
        headers=admin_headers,
        json={"status": "on", "reason": "восстановление"},
    )


def test_conflict_rows_are_persisted(client, admin_headers):
    db = _db()
    try:
        total = db.scalar(select(func.count(Conflict.id))) or 0
        assert total >= 1

        moves = db.scalar(select(func.count(AssetMove.id))) or 0
        assert moves >= 1

        assets = db.scalar(select(func.count(Asset.id))) or 0
        assert assets >= 27
    finally:
        db.close()
