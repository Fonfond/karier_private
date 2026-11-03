"""API-тесты Спринта 2: реестр объектов, типы, карта, путь питания, права."""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.models import Employee, MfaFactor


def _operator_headers(client, secret: str) -> dict:
    db = SessionLocal()
    try:
        employee = db.scalar(select(Employee).where(Employee.tab_no == "000002"))
        db.execute(
            update(MfaFactor).where(MfaFactor.employee_id == employee.id).values(last_counter=None)
        )
        db.commit()
    finally:
        db.close()

    login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
    challenge = login.json()["challenge_token"]
    code = pyotp.TOTP(secret).now()
    verified = client.post("/api/auth/mfa/verify", json={"challenge_token": challenge, "code": code})
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['access_token']}"}


def test_asset_types_seeded(client, admin_headers):
    response = client.get("/api/asset-types", headers=admin_headers)
    assert response.status_code == 200
    codes = {item["code"] for item in response.json()}
    for expected in ("bkru", "ksr", "yaku", "ktp", "dmo", "dmp", "bmp", "ekg", "gen_diesel", "cuckoo"):
        assert expected in codes

    dmo = next(item for item in response.json() if item["code"] == "dmo")
    assert dmo["is_mobile_default"] is True
    assert {p["code"] for p in dmo["port_template"]["ports"]} == {"IN-1", "OUT-1", "OUT-2"}
    assert "power_kw" in dmo["required_attrs"]


def test_active_map_layer_bounds(client, admin_headers):
    response = client.get("/api/map/layers/active", headers=admin_headers)
    assert response.status_code == 200
    layer = response.json()
    assert layer["image_url"].endswith("karier-map.jpg")
    assert layer["width_m"] == 1024.0
    assert layer["height_m"] == 576.0
    assert layer["bounds"] == [[0.0, 0.0], [576.0, 1024.0]]


def test_list_assets_with_filters(client, admin_headers):
    all_assets = client.get("/api/assets", headers=admin_headers).json()
    assert all_assets["total"] >= 16

    ktp_only = client.get("/api/assets?type_code=ktp", headers=admin_headers).json()
    assert ktp_only["total"] >= 2
    assert all(item["type"]["code"] == "ktp" for item in ktp_only["items"])

    mobile = client.get("/api/assets?is_mobile=true", headers=admin_headers).json()
    assert mobile["total"] >= 3
    assert all(item["is_mobile"] for item in mobile["items"])


def test_asset_detail_has_ports(client, admin_headers):
    assets = client.get("/api/assets?type_code=ktp", headers=admin_headers).json()["items"]
    asset_id = assets[0]["id"]
    response = client.get(f"/api/assets/{asset_id}", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["code"].startswith("KTP")
    assert {p["code"] for p in body["ports"]} >= {"IN-1", "OUT-1"}
    assert body["x"] is not None and body["y"] is not None


def test_power_path_chain(client, admin_headers):
    assets = client.get("/api/assets?type_code=ktp", headers=admin_headers).json()["items"]
    ktp_id = next(item["id"] for item in assets if item["code"] == "KTP-14")
    response = client.get(f"/api/assets/{ktp_id}/power-path", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["code"] == "PS-356"
    assert [node["code"] for node in body["chain"]] == ["BKRU-1", "KTP-14"]
    assert body["chain"][-1]["role"] == "asset"


def test_admin_creates_and_deletes_asset(client, admin_headers):
    code = f"TST-{uuid.uuid4().int % 10000}"
    payload = {
        "name": "Тестовая КТП",
        "type_code": "ktp",
        "code": code,
        "x": 500,
        "y": 300,
        "attrs": {"power_kva": 100},
    }
    created = client.post("/api/assets", headers=admin_headers, json=payload)
    assert created.status_code == 201, created.text
    asset_id = created.json()["id"]
    assert created.json()["ports"], "порты должны создаться по шаблону типа"

    patched = client.patch(
        f"/api/assets/{asset_id}",
        headers=admin_headers,
        json={"name": "Тестовая КТП (изменена)", "expected_version": 1},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Тестовая КТП (изменена)"
    assert patched.json()["version"] == 2

    stale = client.patch(
        f"/api/assets/{asset_id}",
        headers=admin_headers,
        json={"name": "Устаревшая правка", "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict.version"

    deleted = client.delete(f"/api/assets/{asset_id}", headers=admin_headers)
    assert deleted.status_code == 200

    gone = client.get(f"/api/assets/{asset_id}", headers=admin_headers)
    assert gone.status_code == 404


def test_out_of_bounds_rejected(client, admin_headers):
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "Вне карты", "type_code": "ktp", "x": 5000, "y": 10},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "asset.out_of_bounds"


def test_required_attrs_validated(client, admin_headers):
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "ДМО без мощности", "type_code": "dmo", "x": 600, "y": 400},
    )
    assert response.status_code == 422
    assert "power_kw" in response.json()["fields"]


def test_duplicate_code_rejected(client, admin_headers):
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "Дубль", "type_code": "ktp", "code": "KTP-14", "x": 100, "y": 100},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "asset.duplicate_code"


def test_operator_reads_but_cannot_create(client, operator_secret):
    headers = _operator_headers(client, operator_secret)

    listing = client.get("/api/assets", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] >= 16

    created = client.post(
        "/api/assets",
        headers=headers,
        json={"name": "Оператор не должен", "type_code": "ktp", "x": 100, "y": 100},
    )
    assert created.status_code == 403
    assert created.json()["code"] == "perm.denied"

    assets = listing.json()["items"]
    deleted = client.delete(f"/api/assets/{assets[0]['id']}", headers=headers)
    assert deleted.status_code == 403


def test_operator_can_move_mobile_asset(client, operator_secret):
    """Перемещение «кукушки» — отдельное право, появится в Спринте 5.

    Здесь фиксируем текущее поведение: правка карточки объекта оператору закрыта.
    """
    headers = _operator_headers(client, operator_secret)
    assets = client.get("/api/assets?is_mobile=true", headers=headers).json()["items"]
    mobile = next(item for item in assets if item["type"]["code"] == "cuckoo")
    response = client.patch(f"/api/assets/{mobile['id']}", headers=headers, json={"x": 10, "y": 10})
    assert response.status_code == 403
