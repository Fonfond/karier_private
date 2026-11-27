"""Контракт ошибки валидации (422): машинные ключи `fields` + подписи `field_labels`.

`fields` — часть API-контракта: по ключу клиент находит поле формы и подсвечивает
его (`src-v2/src/lib/api.ts` превращает ответ в `ApiError.fields`). Русские
подписи должны жить отдельно (`field_labels`), иначе клиент, ждущий
`name`/`type_code`/`x`, ломается молча — именно это и произошло в правках
от 24.11, когда подписи подменили ключи.

Тесты намеренно падают, если в `fields` вернутся русские подписи.
"""

from __future__ import annotations


def _problem(response) -> dict:
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "validation.failed", body
    return body


def test_invalid_name_keeps_machine_key_and_adds_label(client, admin_headers):
    """Пустое имя: в fields — ключ `name`, подпись — только в field_labels."""
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "", "type_code": "ktp"},
    )
    body = _problem(response)

    assert "name" in body["fields"], body
    assert body["fields"]["name"]
    # подписи не подменяют машинные ключи
    assert "Название" not in body["fields"], body
    assert set(body["fields"]) == {"name"}, body
    assert body["field_labels"]["name"] == "Название"
    # detail остаётся читаемым по-русски
    assert body["detail"] == "Название: минимум 2 символа", body["detail"]


def test_missing_type_and_broken_x_use_machine_keys(client, admin_headers):
    """Нет type_code и нечисловой x: ключи `type_code`, `x`, подписи — отдельно."""
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "Объект контракта", "x": "не число"},
    )
    body = _problem(response)

    assert {"type_code", "x"} <= set(body["fields"]), body
    assert body["field_labels"]["type_code"] == "Тип"
    assert body["field_labels"]["x"] == "X"
    assert "Тип" not in body["fields"], body
    assert "X" not in body["fields"], body
    assert len(body["fields"]) == len(body["field_labels"]) == 2, body
    # вторая ошибка сворачивается в «и ещё N», а не теряется
    assert "и ещё 1" in body["detail"], body["detail"]


def test_problem_payload_stays_client_compatible(client, admin_headers):
    """Форма ответа, на которую рассчитывает фронтенд, не изменилась."""
    body = _problem(
        client.post("/api/assets", headers=admin_headers, json={"name": "", "type_code": "ktp"})
    )

    assert isinstance(body["detail"], str) and body["detail"]
    assert body["title"]
    assert body["status"] == 422
    assert "request_id" in body
    for key, value in body["fields"].items():
        assert isinstance(key, str) and isinstance(value, str), (key, value)
    for key, value in body["field_labels"].items():
        assert isinstance(key, str) and isinstance(value, str), (key, value)
