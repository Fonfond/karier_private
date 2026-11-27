"""API-тесты Спринта 4: фото с метаданными, обходы, дефекты, история."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Media


def _asset(client, headers, code: str) -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def _upload_photo(client, headers, asset_id: str, *, purpose: str = "inspection", **extra):
    payload = b"\xff\xd8\xff\xe0test-jpeg-bytes-" + uuid.uuid4().bytes
    data = {
        "purpose": purpose,
        "geo_source": "exif",
        "lat": "56.1234567",
        "lon": "101.7654321",
        "accuracy_m": "8.5",
        "captured_at": "2026-11-03T09:15:00+08:00",
        "width": "1600",
        "height": "1200",
        "watermark": "03.11.2026 09:15 · 56.12346, 101.76543 · Иванов И.И. · таб. 000001 · KTP-14",
        "exif": '{"DateTimeOriginal":"2026:11:03 09:15:00","Make":"Pixel"}',
        **extra,
    }
    return client.post(
        f"/api/assets/{asset_id}/media",
        headers=headers,
        files={"file": ("photo.jpg", payload, "image/jpeg")},
        data=data,
    ), payload


def test_photo_metadata_and_sha256(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    response, payload = _upload_photo(client, admin_headers, asset["id"])
    assert response.status_code == 201, response.text
    media = response.json()

    assert media["sha256"] == hashlib.sha256(payload).hexdigest()
    assert media["geo_source"] == "exif"
    assert media["lat"] == 56.1234567
    assert media["lon"] == 101.7654321
    assert media["author_tab_no"] == "000001"
    assert media["author_name"]
    assert "KTP-14" in (media["watermark_applied"] or "")
    # captured_at хранится в timestamptz и сериализуется в часовом поясе сессии:
    # локально +08, в CI (UTC) — 01:15. Сравниваем момент времени, а не строку.
    captured = datetime.fromisoformat(media["captured_at"].replace("Z", "+00:00"))
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    expected = datetime.fromisoformat("2026-11-03T09:15:00+08:00")
    assert captured.astimezone(timezone.utc) == expected.astimezone(timezone.utc)
    assert media["exif"]["Make"] == "Pixel"
    assert media["width"] == 1600 and media["height"] == 1200

    db = SessionLocal()
    try:
        row = db.get(Media, uuid.UUID(media["id"]))
        assert row is not None
        assert row.sha256 == hashlib.sha256(payload).hexdigest()
        assert row.author_id is not None
    finally:
        db.close()

    file_response = client.get(media["content_url"])
    assert file_response.status_code == 200
    assert file_response.content == payload


def test_photo_rejects_non_image(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    response = client.post(
        f"/api/assets/{asset['id']}/media",
        headers=admin_headers,
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        data={"purpose": "inspection"},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "media.bad_type"


def test_inspection_flow(client, admin_headers):
    assets = client.get("/api/assets?limit=1000", headers=admin_headers).json()["items"]
    chosen = [item["id"] for item in assets[:3]]

    created = client.post(
        "/api/inspections",
        headers=admin_headers,
        json={"kind": "walk", "asset_ids": chosen, "title": "Обход тестовый"},
    )
    assert created.status_code == 201, created.text
    inspection = created.json()
    assert inspection["total"] == 3
    assert inspection["checked"] == 0
    assert all(item["result"] is None for item in inspection["items"])

    inspection_id = inspection["id"]
    first = inspection["items"][0]["asset"]["id"]

    ok = client.post(
        f"/api/inspections/{inspection_id}/items",
        headers=admin_headers,
        json={"asset_id": first, "result": "ok", "comment": "без замечаний"},
    )
    assert ok.status_code == 200
    assert ok.json()["checked"] == 1

    defect_item = inspection["items"][1]["asset"]["id"]
    bad = client.post(
        f"/api/inspections/{inspection_id}/items",
        headers=admin_headers,
        json={"asset_id": defect_item, "result": "defect", "comment": "трещина изолятора"},
    )
    assert bad.status_code == 200
    assert bad.json()["checked"] == 2

    submitted = client.post(f"/api/inspections/{inspection_id}/submit", headers=admin_headers)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"

    repeated = client.post(
        f"/api/inspections/{inspection_id}/items",
        headers=admin_headers,
        json={"asset_id": first, "result": "ok"},
    )
    assert repeated.status_code == 409

    mine = client.get("/api/inspections?mine=true", headers=admin_headers)
    assert mine.status_code == 200
    assert any(item["id"] == inspection_id for item in mine.json()["items"])


def test_defect_requires_after_photo(client, admin_headers):
    asset = _asset(client, admin_headers, "KTП-14".replace("П", "P")) if False else _asset(
        client, admin_headers, "KTP-14"
    )

    created = client.post(
        "/api/defects",
        headers=admin_headers,
        json={
            "asset_id": asset["id"],
            "severity": "high",
            "description": "Повреждение кабельной разделки",
            "category": "electrical",
        },
    )
    assert created.status_code == 201, created.text
    defect = created.json()
    assert defect["status"] == "open"
    assert defect["severity"] == "high"

    no_photo = client.patch(
        f"/api/defects/{defect['id']}", headers=admin_headers, json={"status": "fixed"}
    )
    assert no_photo.status_code == 422
    assert no_photo.json()["code"] == "defect.photo_required"

    photo, _ = _upload_photo(client, admin_headers, asset["id"], purpose="defect")
    photo_id = photo.json()["id"]

    fixed = client.patch(
        f"/api/defects/{defect['id']}",
        headers=admin_headers,
        json={"status": "fixed", "photo_after_id": photo_id},
    )
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    assert body["status"] == "fixed"
    assert body["photo_after"]["id"] == photo_id
    assert body["fixed_at"] is not None


def test_history_contains_inspection_and_defect(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-15")
    inspection = client.post(
        "/api/inspections",
        headers=admin_headers,
        json={"kind": "targeted", "asset_ids": [asset["id"]]},
    ).json()
    client.post(
        f"/api/inspections/{inspection['id']}/items",
        headers=admin_headers,
        json={"asset_id": asset["id"], "result": "defect", "comment": "нагрев"},
    )
    client.post(
        "/api/defects",
        headers=admin_headers,
        json={"asset_id": asset["id"], "severity": "critical", "description": "Перегрев шины"},
    )

    history = client.get(f"/api/assets/{asset['id']}/history", headers=admin_headers)
    assert history.status_code == 200
    kinds = {entry["kind"] for entry in history.json()["items"]}
    assert "inspection" in kinds
    assert "defect" in kinds


def test_media_list_by_asset(client, admin_headers):
    asset = _asset(client, admin_headers, "DMO-1")
    _upload_photo(client, admin_headers, asset["id"], purpose="install")
    response = client.get(f"/api/assets/{asset['id']}/media", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1
    assert response.json()["items"][0]["purpose"] == "install"
