"""Отмена удаления: объект и связь возвращаются из архива.

Проверяем то, на чём держится Undo/Redo редактора схемы: `POST /assets/{id}/restore`
и `POST /links/{id}/restore`.
"""

from __future__ import annotations

import pyotp


def _graph(client, headers) -> dict:
    response = client.get("/api/topology/graph", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _operator_headers(client, operator_secret: str) -> dict:
    login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body.get("mfa_required") is True, body
    verify = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": body["challenge_token"], "code": pyotp.TOTP(operator_secret).now()},
    )
    assert verify.status_code == 200, verify.text
    return {"Authorization": f"Bearer {verify.json()['access_token']}"}


def test_link_delete_and_restore(client, admin_headers):
    graph = _graph(client, admin_headers)
    assert graph["edges"], "в демо-схеме должна быть хотя бы одна связь"
    edge = graph["edges"][0]
    before = len(graph["edges"])

    deleted = client.delete(f"/api/links/{edge['id']}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text

    after_delete = _graph(client, admin_headers)
    assert len(after_delete["edges"]) == before - 1
    assert all(item["id"] != edge["id"] for item in after_delete["edges"])

    restored = client.post(f"/api/links/{edge['id']}/restore", headers=admin_headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == edge["id"]

    after_restore = _graph(client, admin_headers)
    assert len(after_restore["edges"]) == before
    assert any(item["id"] == edge["id"] for item in after_restore["edges"])


def test_asset_delete_and_restore_brings_links_back(client, admin_headers):
    graph = _graph(client, admin_headers)
    degree: dict[str, int] = {}
    for edge in graph["edges"]:
        degree[edge["from_asset_id"]] = degree.get(edge["from_asset_id"], 0) + 1
        degree[edge["to_asset_id"]] = degree.get(edge["to_asset_id"], 0) + 1

    node = next((item for item in graph["nodes"] if degree.get(item["id"], 0) > 0), None)
    if node is None:
        node = next((item for item in graph["nodes"] if degree.get(item["id"], 0) > 0), graph["nodes"][0])
    asset_id = node["id"]
    touched = degree.get(asset_id, 0)
    edges_before = len(graph["edges"])

    deleted = client.delete(f"/api/assets/{asset_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text

    gone = client.get(f"/api/assets/{asset_id}", headers=admin_headers)
    assert gone.status_code == 404, gone.text

    after_delete = _graph(client, admin_headers)
    assert len(after_delete["edges"]) == edges_before - touched

    restored = client.post(f"/api/assets/{asset_id}/restore", headers=admin_headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == asset_id

    after_restore = _graph(client, admin_headers)
    assert len(after_restore["edges"]) == edges_before

    # повторное удаление и восстановление из истории тоже должно работать
    again = client.delete(f"/api/assets/{asset_id}", headers=admin_headers)
    assert again.status_code == 200, again.text
    back = client.post(f"/api/assets/{asset_id}/restore", headers=admin_headers)
    assert back.status_code == 200, back.text


def test_restore_requires_authentication(client, admin_headers):
    """Восстановление закрыто авторизацией; ролевые проверки — в тестах RBAC."""
    graph = _graph(client, admin_headers)
    edge = graph["edges"][0]
    asset_id = graph["nodes"][0]["id"]

    anonymous_link = client.post(f"/api/links/{edge['id']}/restore")
    assert anonymous_link.status_code == 401, anonymous_link.text
    anonymous_asset = client.post(f"/api/assets/{asset_id}/restore")
    assert anonymous_asset.status_code == 401, anonymous_asset.text
