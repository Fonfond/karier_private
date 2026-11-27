"""Построение линии: пачки ячеек с секциями, кабели, оборудование на опоре.

Проверяем, что всё созданное живёт в реестре `gis.assets` и связях `gis.links`,
а отмена/повтор (soft-delete + restore) возвращает элементы на место.
"""

from __future__ import annotations

import time

import pyotp


def _active_types(client, headers) -> list[dict]:
    return client.get("/api/asset-types", headers=headers).json()


def _type_by_word(client, headers, words: tuple[str, ...]) -> str:
    types = _active_types(client, headers)
    for item in types:
        name = (item.get("name") or "").lower()
        code = (item.get("code") or "").lower()
        if any(word in name or word in code for word in words):
            return item["code"]
    for item in types:
        if not item.get("is_composite"):
            return item["code"]
    return types[0]["code"]


def _first_asset(client, headers, type_code: str) -> dict | None:
    data = client.get("/api/assets", headers=headers, params={"type_code": type_code}).json()
    return data["items"][0] if data["items"] else None


def _make_contour(client, headers, name: str) -> dict:
    type_code = _type_by_word(client, headers, ("контур", "прочее", "aux"))
    response = client.post(
        "/api/schema/contours",
        headers=headers,
        json={"name": name, "type_code": type_code, "x": 100, "y": 100},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_bulk_cells_numbering_and_sections(client, admin_headers):
    contour = _make_contour(client, admin_headers, "ПС 35-6 (пакет ячеек)")
    body: dict = {"items": []}
    try:
        response = client.post(
            f"/api/schema/assets/{contour['id']}/cells/bulk",
            headers=admin_headers,
            json={
                "count": 30,
                "start": 1,
                "prefix": "Яч. №",
                "section_size": 15,
                "section_prefix": "Секция",
                "role": "outgoing",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["count"] == 30
        assert body["sections"] == ["Секция 1", "Секция 2"]
        names = [item["name"] for item in body["items"]]
        assert names[0] == "Яч. №1"
        assert names[14] == "Яч. №15"
        assert names[15] == "Яч. №16"
        assert names[-1] == "Яч. №30"

        first = client.get(f"/api/assets/{body['items'][0]['id']}", headers=admin_headers).json()
        sixteenth = client.get(f"/api/assets/{body['items'][15]['id']}", headers=admin_headers).json()
        assert first["parent_id"] == contour["id"]
        assert first["attrs"]["section"] == "Секция 1"
        assert first["attrs"]["sequence_no"] == 1
        assert sixteenth["attrs"]["section"] == "Секция 2"
        assert sixteenth["attrs"]["sequence_no"] == 16

        children = client.get(f"/api/assets/{contour['id']}/children", headers=admin_headers).json()
        assert len(children) == 30
    finally:
        data = client.get(f"/api/assets/{contour['id']}/children", headers=admin_headers).json()
        for child in data:
            client.delete(f"/api/schema/assets/{contour['id']}/cells/{child['id']}", headers=admin_headers)
        client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def test_cable_from_cell_to_pole(client, admin_headers):
    pole_type = _type_by_word(client, admin_headers, ("опора", "pole"))
    pole = _first_asset(client, admin_headers, pole_type)
    assert pole is not None, "в демо-данных должна быть опора"

    contour = _make_contour(client, admin_headers, "Контур с фидером")
    cell = client.post(
        f"/api/schema/assets/{contour['id']}/cells",
        headers=admin_headers,
        json={"label": "Яч. №7", "role": "outgoing"},
    ).json()
    try:
        response = client.post(
            f"/api/schema/assets/{cell['id']}/cables",
            headers=admin_headers,
            json={
                "to_asset_id": pole["id"],
                "cable_mark": "Ф-7К",
                "length_m": 120,
                "cross_section_mm2": 35,
            },
        )
        assert response.status_code == 201, response.text
        link = response.json()
        assert link["link_type"] == "cable"
        assert link["cable_mark"] == "Ф-7К"
        assert link["length_m"] == 120

        links = client.get("/api/links", headers=admin_headers, params={"asset_id": cell["id"]}).json()
        assert any(item["id"] == link["id"] for item in links["items"])
    finally:
        for item in client.get("/api/links", headers=admin_headers, params={"asset_id": cell["id"]}).json()["items"]:
            client.delete(f"/api/links/{item['id']}", headers=admin_headers)
        client.delete(f"/api/schema/assets/{contour['id']}/cells/{cell['id']}", headers=admin_headers)
        client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def test_line_equipment_ktp_and_undo_redo(client, admin_headers):
    pole_type = _type_by_word(client, admin_headers, ("опора", "pole"))
    pole = _first_asset(client, admin_headers, pole_type)
    assert pole is not None
    ktp_type = _type_by_word(client, admin_headers, ("ктп", "ktp"))

    created = client.post(
        "/api/schema/line-equipment",
        headers=admin_headers,
        json={"anchor_asset_id": pole["id"], "type_code": ktp_type, "name": "КТП-77", "cable_mark": "Ф-7К"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "КТП-77"
    assert body["link_id"], "оборудование должно быть присоединено к опоре"

    asset = client.get(f"/api/assets/{body['asset_id']}", headers=admin_headers).json()
    assert asset["type"]["code"] == ktp_type
    assert asset["parent_id"] is None
    anchor_full = client.get(f"/api/assets/{pole['id']}", headers=admin_headers).json()
    if anchor_full["schema_x"] is not None:
        assert body["schema_x"] is not None, "оборудование ставится рядом с опорой"

    # Undo: снять связь и убрать объект в архив
    client.delete(f"/api/links/{body['link_id']}", headers=admin_headers)
    client.delete(f"/api/assets/{body['asset_id']}", headers=admin_headers)
    assert client.get(f"/api/assets/{body['asset_id']}", headers=admin_headers).status_code == 404

    # Redo: вернуть объект и связь
    assert client.post(f"/api/assets/{body['asset_id']}/restore", headers=admin_headers).status_code == 200
    assert client.post(f"/api/links/{body['link_id']}/restore", headers=admin_headers).status_code == 200
    links = client.get("/api/links", headers=admin_headers, params={"asset_id": pole["id"]}).json()
    assert any(item["id"] == body["link_id"] for item in links["items"])

    # уборка
    client.delete(f"/api/links/{body['link_id']}", headers=admin_headers)
    client.delete(f"/api/assets/{body['asset_id']}", headers=admin_headers)


def test_bulk_and_equipment_require_admin(client, admin_headers, operator_secret):
    contour = _make_contour(client, admin_headers, "Контур для проверки прав")
    try:
        anonymous = client.post(f"/api/schema/assets/{contour['id']}/cells/bulk", json={"count": 1})
        assert anonymous.status_code == 401

        operator_headers = _operator_headers(client, operator_secret)
        forbidden = client.post(
            f"/api/schema/assets/{contour['id']}/cells/bulk",
            headers=operator_headers,
            json={"count": 1},
        )
        assert forbidden.status_code == 403, forbidden.text

        forbidden_equipment = client.post(
            "/api/schema/line-equipment",
            headers=operator_headers,
            json={"anchor_asset_id": contour["id"], "type_code": "ktp"},
        )
        assert forbidden_equipment.status_code == 403, forbidden_equipment.text
    finally:
        client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def test_feeder_filter_excludes_new_object_without_line(client, admin_headers):
    """Новый объект без привязки к линии не попадает в выборку чужого фидера."""
    feeder = next(
        (
            line
            for line in client.get("/api/lines", headers=admin_headers).json()
            if line["code"] == "ф.21К"
        ),
        None,
    )
    assert feeder is not None, "в демо-данных должен быть фидер ф.21К"
    contour = _make_contour(client, admin_headers, "Контур вне фидеров")
    try:
        in_feeder = client.get(
            "/api/assets", headers=admin_headers, params={"feeder": feeder["code"], "limit": 1000}
        ).json()
        assert contour["id"] not in {item["id"] for item in in_feeder["items"]}

        # объект существует в реестре (карточка по id — без зависимости от limit списка)
        assert client.get(f"/api/assets/{contour['id']}", headers=admin_headers).status_code == 200
    finally:
        client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def _operator_headers(client, operator_secret: str) -> dict:
    for attempt in range(3):
        login = client.post("/api/auth/login", json={"tab_no": "000002", "password": "operator123"})
        assert login.status_code == 200, login.text
        body = login.json()
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
