"""API-тесты Спринта 5: журнал изменений, push/pull, конфликты, перемещения."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    Asset,
    AssetMove,
    AssetType,
    ChangeLog,
    Conflict,
    Defect,
    Employee,
    Pit,
    Role,
    SyncOp,
)


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


# --- S-4: RBAC офлайн-операций и привязка entity к карьеру ------------------

def _role_headers(role_code: str) -> tuple[dict, uuid.UUID]:
    """Токен активного сотрудника с указанной ролью (без пароля/2FA)."""
    db = _db()
    try:
        role = db.scalar(select(Role).where(Role.code == role_code))
        assert role is not None, f"роль {role_code} не найдена"
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"T{uuid.uuid4().hex[:8].upper()}",
            full_name=f"Тест S-4 {role_code}",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role=role_code, session_id=str(uuid.uuid4()))
        return {"Authorization": f"Bearer {token}"}, employee.id
    finally:
        db.close()


def _drop_employee(employee_id: uuid.UUID) -> None:
    db = _db()
    try:
        employee = db.get(Employee, employee_id)
        if employee is not None:
            db.delete(employee)
            db.commit()
    finally:
        db.close()


def _push(client, headers, ops):
    return client.post(
        "/api/sync/push",
        headers=headers,
        json={"device_id": "test-s4", "ops": ops},
    )


def _asset_op(entity_id: str, patch: dict, op: str = "update") -> dict:
    return {
        "op_id": str(uuid.uuid4()),
        "entity": "asset",
        "entity_id": entity_id,
        "op": op,
        "patch": patch,
    }


def _move_op(entity_id: str, x: float, y: float) -> dict:
    return {
        "op_id": str(uuid.uuid4()),
        "entity": "move",
        "entity_id": entity_id,
        "op": "update",
        "patch": {"x": x, "y": y},
    }


def _defect_op(asset_id: str, description: str) -> dict:
    return {
        "op_id": str(uuid.uuid4()),
        "entity": "defect",
        "entity_id": asset_id,
        "op": "insert",
        "patch": {"asset_id": asset_id, "description": description, "severity": "low"},
    }


def test_viewer_forbidden_status_patch(client, admin_headers):
    """viewer без asset.status.edit: push status → 403 с кодом, объект не меняется."""
    asset = _asset(client, admin_headers, "KTP-14")
    headers, employee_id = _role_headers("viewer")
    try:
        response = _push(client, headers, [_asset_op(asset["id"], {"status": "off"})])
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "perm.denied", response.text

        after = client.get(f"/api/assets/{asset['id']}", headers=admin_headers).json()
        assert after["status"] == asset["status"], "запрещённая операция не должна менять объект"
    finally:
        _drop_employee(employee_id)


def test_viewer_and_contractor_forbidden_operations(client, admin_headers):
    """viewer/contractor: move и patch координат запрещены; дефект — только без defect.manage."""
    asset = _asset(client, admin_headers, "KTP-15")
    for role in ("viewer", "contractor"):
        headers, employee_id = _role_headers(role)
        try:
            status_push = _push(client, headers, [_asset_op(asset["id"], {"status": "off"})])
            assert status_push.status_code == 403, (role, status_push.text)

            move_push = _push(client, headers, [_move_op(asset["id"], 100, 100)])
            assert move_push.status_code == 403, (role, move_push.text)

            patch_push = _push(client, headers, [_asset_op(asset["id"], {"x": 100, "y": 100})])
            assert patch_push.status_code == 403, (role, patch_push.text)
        finally:
            _drop_employee(employee_id)

    headers, employee_id = _role_headers("viewer")
    try:
        defect_push = _push(client, headers, [_defect_op(asset["id"], "viewer не должен создавать")])
        assert defect_push.status_code == 403, defect_push.text
        assert defect_push.json()["code"] == "perm.denied"
    finally:
        _drop_employee(employee_id)


def test_operator_cannot_change_name_without_asset_create(client, admin_headers):
    """operator без asset.create: patch name/attrs → 403."""
    asset = _asset(client, admin_headers, "KTP-14")
    headers, employee_id = _role_headers("operator")
    try:
        for patch in ({"name": "Новое имя"}, {"attrs": {"note": "x"}}):
            response = _push(client, headers, [_asset_op(asset["id"], patch)])
            assert response.status_code == 403, response.text
            assert response.json()["code"] == "perm.denied"
    finally:
        _drop_employee(employee_id)


def test_operator_push_status_and_move_applied(client, admin_headers):
    """operator с asset.status.edit/asset.move: валидные операции применяются (200)."""
    asset = _asset(client, admin_headers, "KTP-15")
    mobile = _asset(client, admin_headers, "DMO-1")
    headers, employee_id = _role_headers("operator")
    try:
        new_status = "off" if asset["status"] != "off" else "on"
        status_push = _push(client, headers, [_asset_op(asset["id"], {"status": new_status})])
        assert status_push.status_code == 200, status_push.text
        assert status_push.json()["results"][0]["status"] == "applied"
        client.post(
            f"/api/assets/{asset['id']}/state",
            headers=admin_headers,
            json={"status": asset["status"], "reason": "S-4: возврат статуса"},
        )

        move_push = _push(client, headers, [_move_op(mobile["id"], 310, 210)])
        assert move_push.status_code == 200, move_push.text
        assert move_push.json()["results"][0]["status"] in ("applied", "conflict_won")
        after = client.get(f"/api/assets/{mobile['id']}", headers=admin_headers).json()
        assert (after["x"], after["y"]) == (310.0, 210.0)
    finally:
        _drop_employee(employee_id)
        client.post(
            f"/api/assets/{mobile['id']}/move",
            headers=admin_headers,
            json={"x": mobile["x"], "y": mobile["y"], "note": "S-4: возврат координат"},
        )


def test_contractor_can_insert_defect(client, admin_headers):
    """contractor с defect.manage: дефект из офлайн-очереди применяется."""
    asset = _asset(client, admin_headers, "KTP-14")
    headers, employee_id = _role_headers("contractor")
    description = f"S-4 дефект {uuid.uuid4().hex[:8]}"
    try:
        response = _push(client, headers, [_defect_op(asset["id"], description)])
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["status"] == "applied"

        db = _db()
        try:
            defect = db.scalar(select(Defect).where(Defect.description == description))
            assert defect is not None, "дефект должен появиться в БД"
            defect_id = defect.id
        finally:
            db.close()
        client.delete(f"/api/defects/{defect_id}", headers=admin_headers)
    finally:
        _drop_employee(employee_id)


def test_push_rejects_out_of_bounds_move_and_patch(client, admin_headers):
    """Границы карты: и move, и patch x/y вне карты → rejected (не 500)."""
    mobile = _asset(client, admin_headers, "DMO-1")

    move_response = _push(client, admin_headers, [_move_op(mobile["id"], 5000, 5000)])
    assert move_response.status_code == 200, move_response.text
    move_result = move_response.json()["results"][0]
    assert move_result["status"] == "rejected"
    assert "вне карты" in (move_result["message"] or "").lower()

    patch_response = _push(client, admin_headers, [_asset_op(mobile["id"], {"x": 5000})])
    assert patch_response.status_code == 200, patch_response.text
    patch_result = patch_response.json()["results"][0]
    assert patch_result["status"] == "rejected"
    assert "вне карты" in (patch_result["message"] or "").lower()

    after = client.get(f"/api/assets/{mobile['id']}", headers=admin_headers).json()
    assert (after["x"], after["y"]) == (mobile["x"], mobile["y"])


def test_foreign_pit_entity_returns_404(client, admin_headers):
    """entity_id чужого карьера (asset/move/defect) → 404 до каких-либо изменений."""
    db = _db()
    pit_id = uuid.uuid4()
    foreign_id = uuid.uuid4()
    try:
        asset_type = db.scalar(select(AssetType).where(AssetType.is_active.is_(True)))
        assert asset_type is not None
        pit = Pit(
            id=pit_id,
            code=f"other-{uuid.uuid4().hex[:6]}",
            name="Чужой карьер",
            timezone="UTC",
            crs_name="local",
            is_active=False,
            schema_frame={},
        )
        foreign = Asset(
            id=foreign_id,
            pit_id=pit_id,
            asset_type_id=asset_type.id,
            code=f"FOREIGN-{uuid.uuid4().hex[:6]}",
            name="Чужой объект",
            status="off",
            lifecycle="installed",
            grounded=False,
            is_mobile=False,
            attrs={},
            version=1,
        )
        db.add(pit)
        db.flush()  # без relationship порядок INSERT не гарантирован — карьер раньше объекта
        db.add(foreign)
        db.commit()
    finally:
        db.close()

    try:
        for op in (
            _asset_op(str(foreign_id), {"status": "on"}),
            _move_op(str(foreign_id), 10, 10),
            _defect_op(str(foreign_id), "чужой дефект"),
        ):
            response = _push(client, admin_headers, [op])
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "asset.not_found", response.text
    finally:
        db = _db()
        try:
            db.execute(text("delete from gis.assets where id = :id"), {"id": foreign_id})
            db.execute(text("delete from gis.pits where id = :id"), {"id": pit_id})
            db.commit()
        finally:
            db.close()
