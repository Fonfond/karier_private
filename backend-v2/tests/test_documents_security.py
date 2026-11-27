"""Безопасность документов (S-5): SVG не принимаем и не отдаём «активно».

Проверяем три вещи:
1) заявленный `image/svg+xml` отклоняется по MIME (415);
2) SVG, замаскированный под PNG, отклоняется по содержимому (magic bytes / разметка);
3) даже старая запись в БД с `mime=image/svg+xml` не отдаётся как активный SVG —
   только `application/octet-stream` + `Content-Disposition: attachment`.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import SessionLocal

SVG_PAYLOAD = (
    b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b"<script>alert(1)</script></svg>"
)


def _asset_id(client, headers) -> str:
    items = client.get("/api/assets?limit=1", headers=headers).json()["items"]
    assert items, "в тестовой БД должны быть объекты"
    return items[0]["id"]


def _upload(client, headers, asset_id: str, name: str, payload: bytes, mime: str):
    return client.post(
        f"/api/assets/{asset_id}/documents",
        headers=headers,
        files={"file": (name, payload, mime)},
        data={"doc_type": "other", "title": "Проверка S-5"},
    )


def test_svg_by_mime_rejected(client, admin_headers):
    asset_id = _asset_id(client, admin_headers)
    response = _upload(client, admin_headers, asset_id, "pic.svg", SVG_PAYLOAD, "image/svg+xml")
    assert response.status_code == 415, response.text
    assert response.json()["code"] == "document.bad_type"


def test_svg_disguised_as_png_rejected(client, admin_headers):
    asset_id = _asset_id(client, admin_headers)
    response = _upload(client, admin_headers, asset_id, "fake.png", SVG_PAYLOAD, "image/png")
    assert response.status_code in (415, 422), response.text
    assert response.json()["code"] in ("document.svg_not_allowed", "document.bad_content")


def test_pdf_with_wrong_magic_rejected(client, admin_headers):
    asset_id = _asset_id(client, admin_headers)
    response = _upload(
        client, admin_headers, asset_id, "fake.pdf", b"<html>not a pdf</html>", "application/pdf"
    )
    assert response.status_code in (415, 422), response.text
    assert response.json()["code"] in ("document.bad_content", "document.svg_not_allowed")


def test_svg_document_never_served_as_active(client, admin_headers):
    """Страховка для старых записей: mime в БД может быть каким угодно."""
    asset_id = _asset_id(client, admin_headers)
    created = _upload(
        client, admin_headers, asset_id, "doc.pdf", b"%PDF-1.4\n% S-5 check\n", "application/pdf"
    )
    assert created.status_code == 201, created.text
    document = created.json()

    try:
        db = SessionLocal()
        try:
            db.execute(
                text("update ops.documents set mime = 'image/svg+xml' where id = :id"),
                {"id": document["id"]},
            )
            db.commit()
        finally:
            db.close()

        response = client.get(document["content_url"])
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/octet-stream")
        assert "attachment" in response.headers.get("content-disposition", "").lower()
        assert "svg" not in response.headers["content-type"]
    finally:
        client.delete(f"/api/documents/{document['id']}", headers=admin_headers)
