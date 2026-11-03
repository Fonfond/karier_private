"""API-тесты Спринтов 6–7: дашборд и выгрузки."""

from __future__ import annotations

import uuid


def _asset(client, headers, code: str) -> dict:
    items = client.get("/api/assets?limit=1000", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def test_dashboard_summary(client, admin_headers):
    response = client.get("/api/dashboard/summary", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["assets"]["total"] >= 27
    assert body["assets"]["energized"] + body["assets"]["deenergized"] == body["assets"]["total"]
    assert "by_status" in body["assets"]
    assert "by_severity" in body["defects"]
    assert "week" in body["inspections"]
    assert isinstance(body["mobile"], list)
    assert any(item["code"] == "DMO-1" for item in body["mobile"])


def test_export_xlsx_each_kind(client, admin_headers):
    for kind in ("assets", "defects", "switching", "inspections"):
        token_response = client.post(
            "/api/reports/token", headers=admin_headers, json={"kind": kind}
        )
        assert token_response.status_code == 200, token_response.text
        url = token_response.json()["url"]

        download = client.get(url)
        assert download.status_code == 200, (kind, download.text)
        assert "spreadsheetml" in download.headers["content-type"]
        assert download.content[:2] == b"PK", "xlsx — это zip-архив"
        assert len(download.content) > 3000


def test_passport_pdf(client, admin_headers):
    asset = _asset(client, admin_headers, "KTP-14")
    token_response = client.post(
        "/api/reports/token",
        headers=admin_headers,
        json={"kind": "passport", "asset_id": asset["id"]},
    )
    assert token_response.status_code == 200
    download = client.get(token_response.json()["url"])
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")
    assert len(download.content) > 20000, "паспорт должен содержать карточку, QR и фото"


def test_passport_requires_asset(client, admin_headers):
    response = client.post(
        "/api/reports/token", headers=admin_headers, json={"kind": "passport"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "report.asset_required"


def test_export_token_invalid(client, admin_headers):
    response = client.get("/api/reports/export?token=definitely-not-a-jwt")
    assert response.status_code == 401
    assert response.json()["code"] == "report.bad_token"


def test_export_token_bound_to_employee(client, admin_headers):
    """Токен, подписанный не тем пользователем, не должен выдавать отчёт."""
    from app.core.security import create_export_token

    token = create_export_token("assets", employee_id=str(uuid.uuid4()))
    response = client.get(f"/api/reports/export?token={token}")
    assert response.status_code == 401
