"""Этап 1 модели оборудования «Карьер»: поля паспорта типа и 422 по-русски.

Контракт, на который опирается динамическая форма реестра (этап 1):

* ``GET /api/asset-types?with_fields=1`` отдаёт поля типа
  (``gis.asset_type_fields``) с ``code``/``label``/``data_type``/``required``/``unit`` —
  из них фронтенд строит поля формы;
* ``POST /api/assets`` валидирует ``attrs`` по этим полям и на ошибке отвечает
  422 ``application/problem+json``: ``detail`` — читаемый по-русски,
  ``fields`` — машинные ключи (по ним клиент находит поле формы),
  ``field_labels`` — русские подписи;
* старый клиент продолжает работать: ``attrs`` без объявленных полей типа
  принимаются и сохраняются (201), а ``attr_schema``/``required_attrs``
  синхронизируются с таблицей полей (двойная запись 0015).

Тесты ничего не предполагают о количестве типов в БД и создают свои типы с
уникальными кодами: уборка новых строк — в ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

PROBLEM_JSON = "application/problem+json"
DATA_TYPES = {"number", "integer", "text", "boolean", "date", "select"}
EQUIPMENT_CLASSES = {
    "distribution",
    "transformer_assembly",
    "switching",
    "cell",
    "cable",
    "mobile",
    "line",
    "source",
    "equipment",
}


def _unique(prefix: str) -> str:
    """Код типа, уникальный между прогонами (тестовая БД живёт между запусками)."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create_type(client, headers, **payload) -> dict:
    response = client.post("/api/asset-types", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _types_with_fields(client, headers) -> list[dict]:
    response = client.get("/api/asset-types?with_fields=1", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _type_by_code(types: list[dict], code: str) -> dict:
    item = next((row for row in types if row["code"] == code), None)
    assert item is not None, f"тип {code} не найден в /api/asset-types?with_fields=1"
    return item


def _field_by_code(asset_type: dict, code: str) -> dict:
    field = next((row for row in asset_type["fields"] if row["code"] == code), None)
    assert field is not None, f"у типа {asset_type['code']} нет поля {code}: {asset_type['fields']}"
    return field


def _problem(response, expected_status: int = 422) -> dict:
    """Разобрать problem+json ошибки валидации."""
    assert response.status_code == expected_status, response.text
    assert response.headers["content-type"].startswith(PROBLEM_JSON), response.headers["content-type"]
    body = response.json()
    assert body["code"] == "validation.failed", body
    assert body["status"] == expected_status, body
    assert isinstance(body.get("detail"), str) and body["detail"], body
    return body


def _outgoing_cell_type(code: str) -> dict:
    """Тип «Отходящая ячейка» с обязательной мощностью — как в плане этапа 1."""
    return {
        "code": code,
        "name": "Отходящая ячейка (QA)",
        "category": "equipment",
        "equipment_class": "cell",
        "port_template": {
            "ports": [
                {"code": "IN-1", "name": "Ввод", "kind": "in", "voltage_kv": 6},
                {"code": "OUT-1", "name": "Выход", "kind": "out", "voltage_kv": 6},
            ]
        },
        "fields": [
            {
                "code": "power_kw",
                "label": "Мощность",
                "unit": "кВт",
                "data_type": "number",
                "required": True,
                "group_label": "Мощность",
                "sort_order": 10,
            },
            {
                "code": "cell_no",
                "label": "Номер ячейки",
                "data_type": "integer",
                "required": False,
                "group_label": "Ячейка",
                "sort_order": 20,
            },
        ],
    }


# --- 422 по полям типа: понятный русский текст + машинные ключи ------------


def test_outgoing_cell_without_required_field_returns_russian_422(client, admin_headers):
    """POST без паспорта: 422, detail по-русски, fields — код, field_labels — подпись."""
    type_code = _unique("qa_cell_out")
    _create_type(client, admin_headers, **_outgoing_cell_type(type_code))

    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "Отходящая ячейка QA", "type_code": type_code, "x": 600, "y": 300},
    )
    body = _problem(response)

    # машинный ключ обязательного поля — в fields, подпись — только в field_labels
    assert set(body["fields"]) == {"power_kw"}, body["fields"]
    assert body["fields"]["power_kw"] == "Обязательное поле", body["fields"]
    assert body["field_labels"] == {"power_kw": "Мощность"}, body["field_labels"]
    assert "Мощность" not in body["fields"], "подпись не должна подменять машинный ключ"
    # detail читаемый: имя поля по-русски, без «Проверьте атрибуты объекта»
    assert body["detail"].startswith("Проверьте поля объекта"), body["detail"]
    assert "Мощность" in body["detail"], body["detail"]
    assert "атрибут" not in body["detail"].lower(), body["detail"]


def test_outgoing_cell_with_required_field_created(client, admin_headers):
    """С заполненным паспортом объект создаётся (201), attrs сохраняются."""
    type_code = _unique("qa_cell_out")
    _create_type(client, admin_headers, **_outgoing_cell_type(type_code))

    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={
            "name": "Отходящая ячейка QA (с паспортом)",
            "type_code": type_code,
            "x": 640,
            "y": 320,
            "attrs": {"power_kw": 630, "cell_no": 12},
            "cell_kind": "out",
            "cell_no": 12,
        },
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["type"]["code"] == type_code
    assert asset["type"]["equipment_class"] == "cell"
    assert asset["attrs"] == {"power_kw": 630, "cell_no": 12}, asset["attrs"]
    assert asset["cell_kind"] == "out"
    assert asset["code"], "код объекта должен сгенерироваться из кода типа"
    assert asset["code"].startswith(type_code.upper()), asset["code"]

    # карточка отдаёт тот же паспорт
    fetched = client.get(f"/api/assets/{asset['id']}", headers=admin_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["attrs"]["power_kw"] == 630


def test_field_value_checked_by_data_type_in_russian(client, admin_headers):
    """Неверный тип значения: 422 с русским сообщением у конкретного поля."""
    type_code = _unique("qa_cell_out")
    _create_type(client, admin_headers, **_outgoing_cell_type(type_code))

    body = _problem(
        client.post(
            "/api/assets",
            headers=admin_headers,
            json={
                "name": "Отходящая ячейка QA (строка)",
                "type_code": type_code,
                "attrs": {"power_kw": "много"},
            },
        )
    )
    assert body["fields"] == {"power_kw": "Ожидается число"}, body["fields"]
    assert body["field_labels"]["power_kw"] == "Мощность"
    assert "Мощность" in body["detail"], body["detail"]


def test_patch_asset_validates_fields(client, admin_headers):
    """PATCH с attrs проходит ту же проверку: пустой обязательный паспорт — 422."""
    type_code = _unique("qa_cell_out")
    _create_type(client, admin_headers, **_outgoing_cell_type(type_code))
    created = client.post(
        "/api/assets",
        headers=admin_headers,
        json={
            "name": "Отходящая ячейка QA (правка)",
            "type_code": type_code,
            "attrs": {"power_kw": 400},
        },
    )
    assert created.status_code == 201, created.text
    asset_id = created.json()["id"]

    body = _problem(
        client.patch(
            f"/api/assets/{asset_id}",
            headers=admin_headers,
            json={"attrs": {"cell_no": 7}},
        )
    )
    assert body["fields"]["power_kw"] == "Обязательное поле", body["fields"]
    assert body["field_labels"]["power_kw"] == "Мощность"

    patched = client.patch(
        f"/api/assets/{asset_id}",
        headers=admin_headers,
        json={"attrs": {"power_kw": 500, "cell_no": 7}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["attrs"] == {"power_kw": 500, "cell_no": 7}


# --- контракт GET /api/asset-types?with_fields=1 ---------------------------


def test_asset_types_with_fields_contract(client, admin_headers):
    """?with_fields=1: у каждого поля есть code/label/data_type/required/unit."""
    plain_response = client.get("/api/asset-types", headers=admin_headers)
    assert plain_response.status_code == 200, plain_response.text
    plain_types = plain_response.json()
    assert plain_types, "справочник типов пуст — проверьте seed тестовой БД"
    # без флага старый ответ не растёт: поля не отдаются
    assert all(item["fields"] == [] for item in plain_types), "?with_fields не передан, а fields пришли"

    types = _types_with_fields(client, admin_headers)
    assert {item["code"] for item in types} == {item["code"] for item in plain_types}
    for item in types:
        assert item["equipment_class"] in EQUIPMENT_CLASSES, item
        assert item["group_code"], item
        assert isinstance(item["fields"], list), item
        for field in item["fields"]:
            assert {"code", "label", "data_type", "required", "unit"} <= set(field), field
            assert field["code"], field
            assert isinstance(field["label"], str) and field["label"], field
            assert field["data_type"] in DATA_TYPES, field
            assert isinstance(field["required"], bool), field
            assert field["unit"] is None or isinstance(field["unit"], str), field

    # у полей одного типа коды не повторяются
    for item in types:
        codes = [field["code"] for field in item["fields"]]
        assert len(codes) == len(set(codes)), (item["code"], codes)


def test_cable_type_fields_contract(client, admin_headers):
    """Тип «Кабель» (0015): обязательные поля, единицы, select состояний."""
    cable = _type_by_code(_types_with_fields(client, admin_headers), "cable")
    assert cable["equipment_class"] == "cable", cable
    assert cable["group_code"] == "cables", cable

    codes = {field["code"] for field in cable["fields"]}
    assert {"cable_mark", "length_m", "section_mm2", "voltage_kv", "lifecycle_status"} <= codes, codes

    mark = _field_by_code(cable, "cable_mark")
    assert mark["label"] == "Марка кабеля", mark
    assert mark["data_type"] == "text", mark
    assert mark["required"] is True, mark

    length = _field_by_code(cable, "length_m")
    assert length["label"] == "Длина", length
    assert length["unit"] == "м", length
    assert length["data_type"] == "number", length
    assert length["required"] is True, length

    lifecycle = _field_by_code(cable, "lifecycle_status")
    assert lifecycle["label"] == "Состояние кабеля", lifecycle
    assert lifecycle["data_type"] == "select", lifecycle
    assert set(lifecycle["options"]) == {"installed", "reserve", "repair"}, lifecycle
    assert lifecycle["default_value"] == "installed", lifecycle

    # /asset-types/{id}/fields отдаёт тот же набор, что ?with_fields=1
    response = client.get(f"/api/asset-types/{cable['id']}/fields", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert [field["code"] for field in response.json()] == [field["code"] for field in cable["fields"]]


def test_created_type_fields_are_visible_with_fields(client, admin_headers):
    """Поля, заданные конструктором, видны в ?with_fields=1 с подписями и единицами."""
    type_code = _unique("qa_cell_out")
    _create_type(client, admin_headers, **_outgoing_cell_type(type_code))

    item = _type_by_code(_types_with_fields(client, admin_headers), type_code)
    assert [field["code"] for field in item["fields"]] == ["power_kw", "cell_no"], item["fields"]

    power = _field_by_code(item, "power_kw")
    assert power["label"] == "Мощность", power
    assert power["unit"] == "кВт", power
    assert power["data_type"] == "number", power
    assert power["required"] is True, power
    assert power["group_label"] == "Мощность", power

    cell_no = _field_by_code(item, "cell_no")
    assert cell_no["label"] == "Номер ячейки", cell_no
    assert cell_no["data_type"] == "integer", cell_no
    assert cell_no["required"] is False, cell_no


# --- обратная совместимость: старый attr_schema и старые attrs ---------------


def test_legacy_attr_schema_syncs_to_fields_and_still_stays_required(client, admin_headers):
    """Тип создан старым API (attr_schema/required_attrs): поля синтезируются, 422 сохраняется."""
    type_code = _unique("qa_legacy_kw")
    created = _create_type(
        client,
        admin_headers,
        code=type_code,
        name="Тип со старой схемой (QA)",
        category="aux",
        attr_schema={"power_kw": {"type": "number", "unit": "кВт"}},
        required_attrs=["power_kw"],
    )
    assert created["attr_schema"] == {"power_kw": {"type": "number", "unit": "кВт"}}
    assert created["required_attrs"] == ["power_kw"]

    # двойная запись 0015: из attr_schema появилось поле с русской подписью и unit
    item = _type_by_code(_types_with_fields(client, admin_headers), type_code)
    power = _field_by_code(item, "power_kw")
    assert power["label"] == "Мощность", power
    assert power["unit"] == "кВт", power
    assert power["data_type"] == "number", power
    assert power["required"] is True, power

    # старый клиент без attrs получает прежний 422 с машинным ключом
    body = _problem(
        client.post(
            "/api/assets",
            headers=admin_headers,
            json={"name": "Тип со старой схемой (без паспорта)", "type_code": type_code},
        )
    )
    assert "power_kw" in body["fields"], body
    assert body["field_labels"]["power_kw"] == "Мощность"

    # и с прежним attrs создание работает
    created_asset = client.post(
        "/api/assets",
        headers=admin_headers,
        json={
            "name": "Тип со старой схемой (со паспортом)",
            "type_code": type_code,
            "attrs": {"power_kw": 250},
        },
    )
    assert created_asset.status_code == 201, created_asset.text
    assert created_asset.json()["attrs"]["power_kw"] == 250


def test_legacy_attrs_on_type_without_fields_still_work(client, admin_headers):
    """Тип без объявленных полей: старые attrs принимаются и сохраняются (201)."""
    type_code = _unique("qa_plain")
    created = _create_type(
        client,
        admin_headers,
        code=type_code,
        name="Тип без полей (QA)",
        category="aux",
    )
    assert created["fields"] == [], created["fields"]
    assert created["attr_schema"] == {}
    assert created["required_attrs"] == []

    attrs = {"voltage_kv": 6, "note": "старый клиент", "reserve": True}
    response = client.post(
        "/api/assets",
        headers=admin_headers,
        json={
            "name": "Объект без паспорта (QA)",
            "type_code": type_code,
            "x": 200,
            "y": 200,
            "attrs": attrs,
        },
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["attrs"] == attrs, asset["attrs"]
    assert asset["type"]["code"] == type_code


def test_cable_without_passport_returns_russian_422_and_with_passport_created(client, admin_headers):
    """Сценарий из приёмки UI: кабель без паспорта — 422, с паспортом — 201."""
    cable = _type_by_code(_types_with_fields(client, admin_headers), "cable")
    required_codes = {field["code"] for field in cable["fields"] if field["required"]}
    assert {"cable_mark", "length_m"} <= required_codes, required_codes

    body = _problem(
        client.post(
            "/api/assets",
            headers=admin_headers,
            json={"name": "Кабель QA (без паспорта)", "type_code": "cable"},
        )
    )
    assert set(body["fields"]) == {"cable_mark", "length_m"}, body["fields"]
    assert body["fields"]["cable_mark"] == "Обязательное поле"
    assert body["fields"]["length_m"] == "Обязательное поле"
    assert body["field_labels"]["cable_mark"] == "Марка кабеля", body["field_labels"]
    assert body["field_labels"]["length_m"] == "Длина", body["field_labels"]
    assert "Марка кабеля" in body["detail"], body["detail"]

    created = client.post(
        "/api/assets",
        headers=admin_headers,
        json={
            "name": "Кабель QA (с паспортом)",
            "type_code": "cable",
            "x": 300,
            "y": 400,
            "attrs": {"cable_mark": "АВБбШв 4х25", "length_m": 120, "section_mm2": 25},
        },
    )
    assert created.status_code == 201, created.text
    asset = created.json()
    assert asset["type"]["equipment_class"] == "cable"
    assert asset["attrs"]["cable_mark"] == "АВБбШв 4х25"
    # 0015: для класса cable состояние по умолчанию — installed
    assert asset["lifecycle_status"] == "installed", asset["lifecycle_status"]
