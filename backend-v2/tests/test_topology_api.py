"""API-тесты Спринта 3: расчёт питания, связи, переключения, документы."""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import select, text, update

from app.db.session import SessionLocal
from app.models import Asset, AssetPort, Employee, Link, MfaFactor, SwitchingOp


def _asset_by_code(client, headers, code: str) -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def _db():
    return SessionLocal()


def test_power_path_full_chain(client, admin_headers):
    ktp = _asset_by_code(client, admin_headers, "KTP-14")
    response = client.get(f"/api/assets/{ktp['id']}/power-path", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["energized"] is True
    assert body["source"]["code"] == "PS-356"
    codes = [node["code"] for node in body["chain"]]
    assert codes == ["PS-356", "PS-356-SEC1", "BKRU1-IN1", "BKRU-1", "BKRU1-OUT1", "KTP-14"]
    # подписи связей: линия фидера и марка кабеля
    labels = [node["link_label"] for node in body["chain"] if node["link_label"]]
    assert "ф.21К" in labels
    assert "СБ-3×50" in labels


def test_power_path_breaks_when_cell_off(client, admin_headers):
    cell = _asset_by_code(client, admin_headers, "BKRU1-OUT1")
    ktp = _asset_by_code(client, admin_headers, "KTP-14")

    off = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=admin_headers,
        json={"status": "off", "reason": "проверка расчёта"},
    )
    assert off.status_code == 200, off.text
    assert off.json()["energization_changed"] is True
    assert off.json()["affected_assets"] >= 2

    broken = client.get(f"/api/assets/{ktp['id']}/power-path", headers=admin_headers).json()
    assert broken["energized"] is False
    assert broken["reason"], "должна быть причина отсутствия питания"

    on = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=admin_headers,
        json={"status": "on", "reason": "проверка завершена"},
    )
    assert on.status_code == 200
    restored = client.get(f"/api/assets/{ktp['id']}/power-path", headers=admin_headers).json()
    assert restored["energized"] is True


def test_grounding_requires_reason_and_is_logged(client, admin_headers):
    cell = _asset_by_code(client, admin_headers, "BKRU1-OUT2")

    no_reason = client.post(
        f"/api/assets/{cell['id']}/state", headers=admin_headers, json={"grounded": True}
    )
    assert no_reason.status_code == 422
    assert no_reason.json()["code"] == "state.reason_required"

    grounded = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=admin_headers,
        json={"grounded": True, "reason": "работы на линии"},
    )
    assert grounded.status_code == 200, grounded.text
    assert grounded.json()["asset"]["grounded"] is True

    db = _db()
    try:
        op = db.scalar(
            select(SwitchingOp)
            .where(SwitchingOp.asset_id == uuid.UUID(cell["id"]))
            .order_by(SwitchingOp.performed_at.desc())
        )
        assert op is not None and op.action == "ground_on"
        assert op.reason == "работы на линии"
    finally:
        db.close()

    back = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=admin_headers,
        json={"grounded": False, "reason": "работы окончены"},
    )
    assert back.status_code == 200
    assert back.json()["asset"]["grounded"] is False


def test_topology_graph(client, admin_headers):
    response = client.get("/api/topology/graph", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) >= 27
    assert len(body["edges"]) >= 25
    open_edges = [edge for edge in body["edges"] if edge["state"] == "open"]
    assert open_edges, "на схеме должна быть хотя бы одна разомкнутая связь (резерв)"
    assert any(edge["link_type"] == "jumper" for edge in body["edges"])


def test_cycle_detected_in_topology_issues(client, admin_headers):
    """Обратная связь, вставленная в обход API, должна ловиться проверкой схемы."""
    db = _db()
    try:
        cell = db.scalar(select(Asset).where(Asset.code == "BKRU1-OUT2"))
        bkru = db.scalar(select(Asset).where(Asset.code == "BKRU-1"))
        from_port = db.scalar(
            select(AssetPort).where(AssetPort.asset_id == cell.id, AssetPort.code == "OUT-1")
        )
        to_port = db.scalar(
            select(AssetPort).where(AssetPort.asset_id == bkru.id, AssetPort.code == "IN-2")
        )
        link = Link(
            id=uuid.uuid4(),
            pit_id=cell.pit_id,
            from_port_id=from_port.id,
            to_port_id=to_port.id,
            link_type="busbar",
            feed_role="main",
            state="connected",
            geometry=[],
            attrs={},
            version=1,
        )
        db.add(link)
        db.commit()
        link_id = link.id
    finally:
        db.close()

    issues = client.get("/api/topology/issues", headers=admin_headers).json()
    assert any(issue["code"] == "topology.cycle" for issue in issues)

    db = _db()
    try:
        db.execute(text("delete from gis.links where id = :id"), {"id": str(link_id)})
        db.commit()
    finally:
        db.close()


def test_link_validation(client, admin_headers):
    ktp = _asset_by_code(client, admin_headers, "KTP-14")
    detail = client.get(f"/api/assets/{ktp['id']}", headers=admin_headers).json()
    ports = {port["code"]: port["id"] for port in detail["ports"]}

    duplicate = client.post(
        "/api/links",
        headers=admin_headers,
        json={"from_port_id": ports["OUT-1"], "to_port_id": ports["OUT-1"], "link_type": "cable"},
    )
    assert duplicate.status_code in (400, 409)

    # напряжение 0,4 кВ нельзя соединить с 6 кВ
    cell = _asset_by_code(client, admin_headers, "BKRU1-OUT1")
    cell_detail = client.get(f"/api/assets/{cell['id']}", headers=admin_headers).json()
    cell_ports = {port["code"]: port["id"] for port in cell_detail["ports"]}
    mismatch = client.post(
        "/api/links",
        headers=admin_headers,
        json={
            "from_port_id": ports["OUT-1"],
            "to_port_id": cell_ports["IN-1"],
            "link_type": "cable",
        },
    )
    assert mismatch.status_code in (409, 422)
    assert mismatch.json()["code"] in ("link.voltage_mismatch", "link.duplicate")


def test_operator_cannot_edit_topology(client, operator_secret):
    db = _db()
    try:
        employee = db.scalar(select(Employee).where(Employee.tab_no == "000002"))
        db.execute(update(MfaFactor).where(MfaFactor.employee_id == employee.id).values(last_counter=None))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
    challenge = login.json()["challenge_token"]
    code = pyotp.TOTP(operator_secret).now()
    verified = client.post(
        "/api/auth/mfa/verify", json={"challenge_token": challenge, "code": code}
    )
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}

    response = client.post(
        "/api/links",
        headers=headers,
        json={"from_port_id": str(uuid.uuid4()), "to_port_id": str(uuid.uuid4())},
    )
    assert response.status_code == 403

    # но переключать состояние оператор может
    cell = _asset_by_code(client, headers, "BKRU1-OUT3")
    switch = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=headers,
        json={"status": "off", "reason": "обход: обнаружен нагрев"},
    )
    assert switch.status_code == 200
    restore = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=headers,
        json={"status": "on", "reason": "осмотр завершён"},
    )
    assert restore.status_code == 200


def test_documents_upload_list_and_download(client, admin_headers):
    asset = _asset_by_code(client, admin_headers, "KTP-14")
    payload = b"%PDF-1.4\n% test schematic\n"

    upload = client.post(
        f"/api/assets/{asset['id']}/documents",
        headers=admin_headers,
        files={"file": ("schematic.pdf", payload, "application/pdf")},
        data={"doc_type": "schematic", "title": "Однолинейная схема КТП-14"},
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()
    assert document["doc_type"] == "schematic"
    assert document["content_url"].startswith("/api/documents/")

    listing = client.get(f"/api/assets/{asset['id']}/documents", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    download = client.get(document["content_url"])
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")

    deleted = client.delete(f"/api/documents/{document['id']}", headers=admin_headers)
    assert deleted.status_code == 200
    gone = client.get(f"/api/documents/{document['id']}/file?token=bad")
    assert gone.status_code == 404


def test_operator_cannot_upload_documents(client, operator_secret):
    db = _db()
    try:
        employee = db.scalar(select(Employee).where(Employee.tab_no == "000002"))
        db.execute(update(MfaFactor).where(MfaFactor.employee_id == employee.id).values(last_counter=None))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
    code = pyotp.TOTP(operator_secret).now()
    verified = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": login.json()["challenge_token"], "code": code},
    )
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}
    asset = _asset_by_code(client, headers, "KTP-14")

    response = client.post(
        f"/api/assets/{asset['id']}/documents",
        headers=headers,
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        data={"doc_type": "manual"},
    )
    assert response.status_code == 403
