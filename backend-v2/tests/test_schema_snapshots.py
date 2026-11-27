"""Снимки схемы: создание, просмотр, публикация и неизменяемость.

Q-6: «черновик → публикация → снимки схемы». Проверяем, что снимок фиксирует
состояние на дату, не меняется вместе с живой схемой и что публиковать может
только администратор.
"""

from __future__ import annotations

import time

import pyotp


def _create_snapshot(client, headers, title: str = "Схема на проверку", comment: str | None = None):
    payload = {"title": title}
    if comment:
        payload["comment"] = comment
    response = client.post("/api/topology/snapshots", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _graph_edges(client, headers) -> int:
    response = client.get("/api/topology/graph", headers=headers)
    assert response.status_code == 200, response.text
    return len(response.json()["edges"])


def test_create_list_and_read_snapshot(client, admin_headers):
    created = _create_snapshot(client, admin_headers, "План сети на 23.11", "Перед переключениями")

    assert created["status"] == "draft"
    assert created["title"] == "План сети на 23.11"
    assert created["comment"] == "Перед переключениями"
    assert created["created_by_name"]
    payload = created["payload"]
    assert payload["schema_version"] == 1
    assert payload["pit"]["name"]
    assert "frame" in payload
    assert payload["counts"]["edges"] == _graph_edges(client, admin_headers)
    assert payload["counts"]["nodes"] == len(payload["graph"]["nodes"])

    listing = client.get("/api/topology/snapshots", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] >= 1
    assert any(item["id"] == created["id"] for item in body["items"])
    brief = next(item for item in body["items"] if item["id"] == created["id"])
    assert "payload" not in brief
    assert brief["counts"]["edges"] == payload["counts"]["edges"]

    detail = client.get(f"/api/topology/snapshots/{created['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["payload"]["counts"] == payload["counts"]


def test_publish_sets_author_and_is_idempotent_guarded(client, admin_headers):
    created = _create_snapshot(client, admin_headers, "Версия для публикации")

    published = client.post(f"/api/topology/snapshots/{created['id']}/publish", headers=admin_headers)
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "published"
    assert body["published_at"]
    assert body["published_by"]
    assert body["published_by_name"]

    listing = client.get("/api/topology/snapshots", headers=admin_headers).json()
    assert listing["published_id"] == created["id"]

    again = client.post(f"/api/topology/snapshots/{created['id']}/publish", headers=admin_headers)
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "schema_snapshot.already_published"


def test_snapshot_stays_unchanged_after_schema_edit(client, admin_headers):
    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    assert graph["edges"], "для проверки нужна хотя бы одна связь"
    edge = graph["edges"][0]

    created = _create_snapshot(client, admin_headers, "До удаления связи")
    captured_edges = created["payload"]["counts"]["edges"]

    deleted = client.delete(f"/api/links/{edge['id']}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    try:
        assert _graph_edges(client, admin_headers) == captured_edges - 1

        stored = client.get(f"/api/topology/snapshots/{created['id']}", headers=admin_headers)
        assert stored.status_code == 200, stored.text
        assert stored.json()["payload"]["counts"]["edges"] == captured_edges
        ids = {item["id"] for item in stored.json()["payload"]["graph"]["edges"]}
        assert edge["id"] in ids
    finally:
        restored = client.post(f"/api/links/{edge['id']}/restore", headers=admin_headers)
        assert restored.status_code == 200, restored.text


def test_snapshot_endpoints_require_authentication(client, admin_headers):
    assert client.get("/api/topology/snapshots").status_code == 401
    assert client.post("/api/topology/snapshots", json={"title": "Без токена"}).status_code == 401
    assert client.post("/api/topology/snapshots/publish").status_code in (401, 405)


def test_snapshot_title_whitespace_only_rejected(client, admin_headers):
    """«  » проходит min_length=2 по сырой строке, но после strip название пустое."""
    response = client.post("/api/topology/snapshots", headers=admin_headers, json={"title": "  "})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "schema_snapshot.title_empty", response.text


def test_snapshot_title_and_comment_are_trimmed(client, admin_headers):
    created = _create_snapshot(client, admin_headers, "  План сети на 24.11  ", "  перед переключениями  ")
    assert created["title"] == "План сети на 24.11"
    assert created["comment"] == "перед переключениями"


def _operator_headers(client, operator_secret: str) -> dict:
    """Вход оператора с TOTP; при совпадении окна кода ждём следующее окно."""
    for attempt in range(3):
        login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
        assert login.status_code == 200, login.text
        body = login.json()
        assert body.get("mfa_required") is True, body
        verify = client.post(
            "/api/auth/mfa/verify",
            json={"challenge_token": body["challenge_token"], "code": pyotp.TOTP(operator_secret).now()},
        )
        if verify.status_code == 200:
            return {"Authorization": f"Bearer {verify.json()['access_token']}"}
        if verify.status_code == 400 and attempt < 2:
            time.sleep(31 - (time.time() % 30) + 0.5)
            continue
        assert verify.status_code == 200, verify.text
    raise AssertionError("не удалось войти оператором")


def test_publish_requires_admin_role(client, admin_headers, operator_secret):
    created = _create_snapshot(client, admin_headers, "Версия для ролевой проверки")
    operator_headers = _operator_headers(client, operator_secret)

    forbidden = client.post(
        f"/api/topology/snapshots/{created['id']}/publish", headers=operator_headers
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "perm.denied"

    listing = client.get("/api/topology/snapshots", headers=operator_headers)
    assert listing.status_code == 200, listing.text
