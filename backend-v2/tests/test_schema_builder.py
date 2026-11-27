"""Сборка схемы: постановка из реестра, контуры, ячейки и связи.

Проверяем, что всё, что появляется на схеме, живёт в реестре `gis.assets`,
и что существующие объекты не дублируются.
"""

from __future__ import annotations

import time
import uuid

import pyotp
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AssetPort, Line
from app.services import schema_blocks as blocks_service


def _active_type(client, headers, exclude_composite: bool = True) -> str:
    types = client.get("/api/asset-types", headers=headers).json()
    for item in types:
        if item.get("is_composite") and exclude_composite:
            continue
        return item["code"]
    return types[0]["code"]


def _asset_count(client, headers) -> int:
    return client.get("/api/assets", headers=headers).json()["total"]


def test_place_existing_asset_does_not_duplicate(client, admin_headers):
    type_code = _active_type(client, admin_headers)
    created = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": "Объект для схемы", "type_code": type_code},
    )
    assert created.status_code == 201, created.text
    asset = created.json()
    assert asset["schema_x"] is None
    before = _asset_count(client, admin_headers)

    placed = client.post(
        f"/api/schema/assets/{asset['id']}/place",
        headers=admin_headers,
        json={"x": 240, "y": 160},
    )
    assert placed.status_code == 200, placed.text
    assert placed.json()["schema_x"] == 240
    assert placed.json()["schema_y"] == 160
    assert _asset_count(client, admin_headers) == before, "постановка не должна создавать дубль"

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    assert any(node["id"] == asset["id"] for node in graph["nodes"])

    client.delete(f"/api/assets/{asset['id']}", headers=admin_headers)


def test_contour_creates_registry_asset_and_block(client, admin_headers):
    type_code = _active_type(client, admin_headers)
    before = _asset_count(client, admin_headers)

    created = client.post(
        "/api/schema/contours",
        headers=admin_headers,
        json={
            "name": "Контур РУ-2",
            "type_code": type_code,
            "x": 400,
            "y": 200,
            "width": 360,
            "height": 240,
            "comment": "Собрано на схеме",
        },
    )
    assert created.status_code == 201, created.text
    contour = created.json()
    assert contour["width"] == 360 and contour["height"] == 240
    assert _asset_count(client, admin_headers) == before + 1

    asset = client.get(f"/api/assets/{contour['id']}", headers=admin_headers)
    assert asset.status_code == 200, asset.text
    body = asset.json()
    assert body["attrs"]["block_code"] == "contour"
    assert body["attrs"]["contour_w"] == 360
    assert body["schema_x"] == 400
    assert body["ports"], "у контура должны быть порты от типа"

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    block = next((item for item in graph["blocks"] if item["asset_id"] == contour["id"]), None)
    assert block is not None, "контур должен попасть в блоки схемы"
    assert block["kind"] == "contour"
    assert block["width"] == 360 and block["height"] == 240
    # контейнер обязан быть и узлом (иначе редактор его не отрисует), и блоком
    assert any(node["id"] == contour["id"] for node in graph["nodes"])

    # отмена создания контура и повтор — через архив/восстановление
    deleted = client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    restored = client.post(f"/api/assets/{contour['id']}/restore", headers=admin_headers)
    assert restored.status_code == 200, restored.text
    graph_again = client.get("/api/topology/graph", headers=admin_headers).json()
    assert any(item["asset_id"] == contour["id"] for item in graph_again["blocks"])

    client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def test_cell_inside_contour_is_in_registry(client, admin_headers):
    type_code = _active_type(client, admin_headers)
    contour = client.post(
        "/api/schema/contours",
        headers=admin_headers,
        json={"name": "Контур с ячейкой", "type_code": type_code, "x": 100, "y": 100},
    ).json()

    cell = client.post(
        f"/api/schema/assets/{contour['id']}/cells",
        headers=admin_headers,
        json={"label": "ф.21к", "role": "outgoing", "x": 140, "y": 180},
    )
    assert cell.status_code == 201, cell.text
    cell_id = cell.json()["id"]

    asset = client.get(f"/api/assets/{cell_id}", headers=admin_headers)
    assert asset.status_code == 200, asset.text
    assert asset.json()["parent_id"] == contour["id"]

    children = client.get(f"/api/assets/{contour['id']}/children", headers=admin_headers)
    assert children.status_code == 200, children.text
    assert any(item["id"] == cell_id for item in children.json())

    graph = client.get("/api/topology/graph", headers=admin_headers).json()
    block = next(item for item in graph["blocks"] if item["asset_id"] == contour["id"])
    assert any(child["id"] == cell_id for child in block["children"])

    # перемычку между ячейками одного блока создаём второй ячейкой
    second = client.post(
        f"/api/schema/assets/{contour['id']}/cells",
        headers=admin_headers,
        json={"label": "ф.22к", "role": "outgoing"},
    ).json()
    jumper = client.post(
        f"/api/schema/assets/{contour['id']}/jumpers",
        headers=admin_headers,
        json={"from_cell_id": cell_id, "to_cell_id": second["id"], "label": "СВ"},
    )
    assert jumper.status_code in (200, 201), jumper.text

    # уборка: связь и обе ячейки, затем контур
    links = client.get("/api/links", headers=admin_headers, params={"asset_id": contour["id"]})
    for item in links.json()["items"]:
        client.delete(f"/api/links/{item['id']}", headers=admin_headers)
    client.delete(f"/api/schema/assets/{contour['id']}/cells/{second['id']}", headers=admin_headers)
    client.delete(f"/api/schema/assets/{contour['id']}/cells/{cell_id}", headers=admin_headers)
    client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def test_last_cell_of_contour_can_be_removed(client, admin_headers):
    """Контур — пустой контейнер: из него можно убрать единственную ячейку.

    Иначе отмена добавления ячейки (Ctrl+Z) упирается в 409 block.last_cell.
    """
    type_code = _active_type(client, admin_headers)
    contour = client.post(
        "/api/schema/contours",
        headers=admin_headers,
        json={"name": "Контур с одной ячейкой", "type_code": type_code, "x": 60, "y": 60},
    ).json()
    cell = client.post(
        f"/api/schema/assets/{contour['id']}/cells",
        headers=admin_headers,
        json={"label": "единственная"},
    ).json()

    removed = client.delete(
        f"/api/schema/assets/{contour['id']}/cells/{cell['id']}", headers=admin_headers
    )
    assert removed.status_code == 200, removed.text

    client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)

def test_cell_type_falls_back_when_default_missing():
    """В рабочей базе нет типа `cell` — резолвер обязан найти активный аналог."""
    db = SessionLocal()
    try:
        resolved = blocks_service._resolve_type(db, "cell")
        assert resolved is not None
        assert resolved.is_active is True
        fallback = blocks_service._resolve_type(db, "no_such_type")
        assert fallback is not None and fallback.is_active is True
    finally:
        db.close()


def test_place_requires_admin(client, admin_headers, operator_secret):
    asset = client.get("/api/assets", headers=admin_headers).json()["items"][0]
    anonymous = client.post(f"/api/schema/assets/{asset['id']}/place", json={"x": 10, "y": 10})
    assert anonymous.status_code == 401

    operator_headers = _operator_headers(client, operator_secret)
    forbidden = client.post(
        f"/api/schema/assets/{asset['id']}/place",
        headers=operator_headers,
        json={"x": 10, "y": 10},
    )
    assert forbidden.status_code == 403, forbidden.text


def test_restore_child_of_archived_parent_conflicts(client, admin_headers):
    """Ребёнка нельзя вернуть, пока родитель в архиве: иерархия порвалась бы.

    Позитивный сценарий рядом: после возврата родителя тот же ребёнок
    восстанавливается штатно (200), т.е. новая проверка не блокирует обычный Undo.
    """
    type_code = _active_type(client, admin_headers)
    contour = client.post(
        "/api/schema/contours",
        headers=admin_headers,
        json={"name": "Контур в архив", "type_code": type_code, "x": 240, "y": 240},
    ).json()
    cell = client.post(
        f"/api/schema/assets/{contour['id']}/cells",
        headers=admin_headers,
        json={"label": "ячейка в архиве"},
    ).json()

    # сначала в архив уходит ребёнок, затем родитель
    assert client.delete(f"/api/assets/{cell['id']}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/assets/{contour['id']}", headers=admin_headers).status_code == 200

    blocked = client.post(f"/api/assets/{cell['id']}/restore", headers=admin_headers)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "asset.parent_archived"

    # родитель вернулся — ребёнок восстанавливается как раньше
    assert client.post(f"/api/assets/{contour['id']}/restore", headers=admin_headers).status_code == 200
    assert client.post(f"/api/assets/{cell['id']}/restore", headers=admin_headers).status_code == 200

    client.delete(f"/api/assets/{cell['id']}", headers=admin_headers)
    client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)


def _make_contour(client, headers, name: str, x: float = 100, y: float = 100) -> dict:
    type_code = _active_type(client, headers)
    response = client.post(
        "/api/schema/contours",
        headers=headers,
        json={"name": name, "type_code": type_code, "x": x, "y": y},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _make_cell(client, headers, contour_id: str, label: str) -> dict:
    response = client.post(
        f"/api/schema/assets/{contour_id}/cells",
        headers=headers,
        json={"label": label},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _block_children(client, headers, block_id: str) -> set[str]:
    graph = client.get("/api/topology/graph", headers=headers).json()
    block = next((item for item in graph["blocks"] if item["asset_id"] == block_id), None)
    return {child["id"] for child in (block or {}).get("children", [])}


def _make_root_asset(client, headers, name: str) -> dict:
    type_code = _active_type(client, headers)
    response = client.post(
        "/api/assets",
        headers=headers,
        json={"name": name, "type_code": type_code},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _delete_container(client, headers, contour_id: str, cell_ids: list[str]) -> None:
    links = client.get("/api/links", headers=headers, params={"asset_id": contour_id}).json()
    for item in links["items"]:
        client.delete(f"/api/links/{item['id']}", headers=headers)
    for cell_id in cell_ids:
        client.delete(f"/api/schema/assets/{contour_id}/cells/{cell_id}", headers=headers)
    client.delete(f"/api/assets/{contour_id}", headers=headers)


def test_relocate_cell_between_contours_keeps_links_and_ports(client, admin_headers):
    """Перенос ячейки в другой контур: меняются родители, связи и порты целы."""
    contour_a = _make_contour(client, admin_headers, "Контур-источник A")
    contour_b = _make_contour(client, admin_headers, "Контур-приёмник B")
    cell = _make_cell(client, admin_headers, contour_a["id"], "ф.31к")
    receiver = _make_root_asset(client, admin_headers, "Приёмник кабеля")

    cable = client.post(
        f"/api/schema/assets/{cell['id']}/cables",
        headers=admin_headers,
        json={"to_asset_id": receiver["id"], "cable_mark": "АВБбШв 4×25"},
    )
    assert cable.status_code == 201, cable.text
    link_id = cable.json()["id"]
    before_count = _asset_count(client, admin_headers)
    ports_before = sorted(
        port["id"] for port in client.get(f"/api/assets/{cell['id']}", headers=admin_headers).json()["ports"]
    )

    moved = client.post(
        f"/api/schema/assets/{cell['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour_b["id"]},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["asset"]["parent_id"] == contour_b["id"]
    assert body["old_parent_id"] == contour_a["id"]
    assert body["old_block_id"] == contour_a["id"]
    assert body["warnings"] == []

    ports_after = sorted(
        port["id"] for port in client.get(f"/api/assets/{cell['id']}", headers=admin_headers).json()["ports"]
    )
    assert ports_after == ports_before, "порты при переносе не пересоздаются"
    links = client.get(
        "/api/links", headers=admin_headers, params={"asset_id": cell["id"]}
    ).json()["items"]
    assert any(item["id"] == link_id for item in links), "связь сохраняется"

    assert cell["id"] not in _block_children(client, admin_headers, contour_a["id"])
    assert cell["id"] in _block_children(client, admin_headers, contour_b["id"])
    assert _asset_count(client, admin_headers) == before_count, "перенос не создаёт дублей в реестре"

    client.delete(f"/api/links/{link_id}", headers=admin_headers)
    _delete_container(client, admin_headers, contour_b["id"], [cell["id"]])
    _delete_container(client, admin_headers, contour_a["id"], [])
    client.delete(f"/api/assets/{receiver['id']}", headers=admin_headers)


def test_relocate_jumper_break_requires_confirmation(client, admin_headers):
    """Перемычка между ячейками блока — повод спросить подтверждение."""
    contour_a = _make_contour(client, admin_headers, "Контур с перемычкой")
    contour_b = _make_contour(client, admin_headers, "Контур-приёмник перемычки")
    first = _make_cell(client, admin_headers, contour_a["id"], "ф.41к")
    second = _make_cell(client, admin_headers, contour_a["id"], "ф.42к")
    jumper = client.post(
        f"/api/schema/assets/{contour_a['id']}/jumpers",
        headers=admin_headers,
        json={"from_cell_id": first["id"], "to_cell_id": second["id"], "label": "СВ"},
    )
    assert jumper.status_code in (200, 201), jumper.text

    denied = client.post(
        f"/api/schema/assets/{first['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour_b["id"]},
    )
    assert denied.status_code == 409, denied.text
    problem = denied.json()
    assert problem["code"] == "schema.move.confirmation_required"
    assert "Перемычк" in problem["detail"]
    assert problem["fields"]["requires_confirm"] == "true"
    assert first["id"] in _block_children(client, admin_headers, contour_a["id"]), "отмена не меняет данные"

    confirmed = client.post(
        f"/api/schema/assets/{first['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour_b["id"], "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert any("Перемычк" in warning for warning in confirmed.json()["warnings"])
    assert first["id"] in _block_children(client, admin_headers, contour_b["id"])

    links = client.get(
        "/api/links", headers=admin_headers, params={"asset_id": contour_a["id"]}
    ).json()
    for item in links["items"]:
        client.delete(f"/api/links/{item['id']}", headers=admin_headers)
    _delete_container(client, admin_headers, contour_b["id"], [first["id"]])
    _delete_container(client, admin_headers, contour_a["id"], [second["id"]])


def test_relocate_invalid_target_is_atomic(client, admin_headers):
    """Недопустимый перенос — понятная ошибка, данные не меняются."""
    contour = _make_contour(client, admin_headers, "Контур для атомарности")
    cell = _make_cell(client, admin_headers, contour["id"], "ф.51к")
    other = _make_cell(client, admin_headers, contour["id"], "ф.52к")
    before = client.get(f"/api/assets/{cell['id']}", headers=admin_headers).json()

    wrong_target = client.post(
        f"/api/schema/assets/{cell['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": other["id"]},
    )
    assert wrong_target.status_code == 400, wrong_target.text
    assert wrong_target.json()["code"] == "schema.move.not_container"

    into_self = client.post(
        f"/api/schema/assets/{contour['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour["id"]},
    )
    assert into_self.status_code == 400, into_self.text
    assert into_self.json()["code"] in ("schema.move.self", "schema.move.container")

    after = client.get(f"/api/assets/{cell['id']}", headers=admin_headers).json()
    assert after["parent_id"] == before["parent_id"]
    assert after["version"] == before["version"], "неудачный перенос не меняет версию объекта"

    _delete_container(client, admin_headers, contour["id"], [cell["id"], other["id"]])


def test_relocate_rejects_voltage_mismatch(client, admin_headers):
    """Напряжение объекта и контейнера не совпадает — понятный 409, данные целы."""
    contour_a = _make_contour(client, admin_headers, "Контур 6 кВ")
    contour_b = _make_contour(client, admin_headers, "Контур 35 кВ")
    cell = _make_cell(client, admin_headers, contour_a["id"], "ф.61к")
    assert (
        client.post(f"/api/assets/{cell['id']}/ports/ensure", headers=admin_headers).status_code
        == 200
    )

    db = SessionLocal()
    try:
        cell_ports = list(
            db.scalars(select(AssetPort).where(AssetPort.asset_id == uuid.UUID(cell["id"])))
        )
        target_ports = list(
            db.scalars(select(AssetPort).where(AssetPort.asset_id == uuid.UUID(contour_b["id"])))
        )
        assert cell_ports and target_ports
        for port in cell_ports:
            port.nominal_voltage_kv = 6
        for port in target_ports:
            port.nominal_voltage_kv = 35
        db.commit()
    finally:
        db.close()

    denied = client.post(
        f"/api/schema/assets/{cell['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour_b["id"]},
    )
    assert denied.status_code == 409, denied.text
    problem = denied.json()
    assert problem["code"] == "schema.move.voltage_mismatch"
    assert "6" in problem["detail"] and "35" in problem["detail"]
    assert cell["id"] in _block_children(client, admin_headers, contour_a["id"])

    _delete_container(client, admin_headers, contour_a["id"], [cell["id"]])
    _delete_container(client, admin_headers, contour_b["id"], [])


def test_relocate_feeder_change_requires_confirmation(client, admin_headers):
    """Перенос между линиями (фидерами) — отдельное предупреждение S-8."""
    suffix = uuid.uuid4().hex[:6]
    line_a = client.post(
        "/api/lines",
        headers=admin_headers,
        json={"code": f"F-A-{suffix}", "name": "Фидер A", "kind": "cable"},
    )
    line_b = client.post(
        "/api/lines",
        headers=admin_headers,
        json={"code": f"F-B-{suffix}", "name": "Фидер B", "kind": "cable"},
    )
    assert line_a.status_code == 201 and line_b.status_code == 201, (line_a.text, line_b.text)
    contour_a = _make_contour(client, admin_headers, "Контур фидера A")
    contour_b = _make_contour(client, admin_headers, "Контур фидера B")
    cell_a = _make_cell(client, admin_headers, contour_a["id"], "ф.71к")
    cell_b = _make_cell(client, admin_headers, contour_b["id"], "ф.72к")
    sink_a = _make_root_asset(client, admin_headers, "Приёмник фидера A")
    sink_b = _make_root_asset(client, admin_headers, "Приёмник фидера B")
    cable_a = client.post(
        f"/api/schema/assets/{cell_a['id']}/cables",
        headers=admin_headers,
        json={"to_asset_id": sink_a["id"]},
    )
    cable_b = client.post(
        f"/api/schema/assets/{cell_b['id']}/cables",
        headers=admin_headers,
        json={"to_asset_id": sink_b["id"]},
    )
    assert cable_a.status_code == 201 and cable_b.status_code == 201
    for opened, line in ((cable_a, line_a), (cable_b, line_b)):
        patched = client.patch(
            f"/api/links/{opened.json()['id']}",
            headers=admin_headers,
            json={"line_id": line.json()["id"]},
        )
        assert patched.status_code == 200, patched.text

    denied = client.post(
        f"/api/schema/assets/{cell_a['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour_b["id"]},
    )
    assert denied.status_code == 409, denied.text
    problem = denied.json()
    assert problem["code"] == "schema.move.confirmation_required"
    assert "линии" in problem["detail"] or "фидер" in problem["detail"].lower()

    confirmed = client.post(
        f"/api/schema/assets/{cell_a['id']}/relocate",
        headers=admin_headers,
        json={"target_asset_id": contour_b["id"], "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert any("линии" in warning or "фидер" in warning.lower() for warning in confirmed.json()["warnings"])

    client.delete(f"/api/links/{cable_a.json()['id']}", headers=admin_headers)
    client.delete(f"/api/links/{cable_b.json()['id']}", headers=admin_headers)
    _delete_container(client, admin_headers, contour_b["id"], [cell_a["id"], cell_b["id"]])
    _delete_container(client, admin_headers, contour_a["id"], [])
    client.delete(f"/api/assets/{sink_a['id']}", headers=admin_headers)
    client.delete(f"/api/assets/{sink_b['id']}", headers=admin_headers)
    db = SessionLocal()
    try:
        for line_id in (line_a.json()["id"], line_b.json()["id"]):
            line = db.get(Line, uuid.UUID(line_id))
            if line is not None:
                db.delete(line)
        db.commit()
    finally:
        db.close()


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


def test_bulk_cells_skip_required_attrs_of_cell_type(client, admin_headers):
    """Пачка ячеек создаётся, даже если тип-аналог ячейки требует атрибуты.

    Регрессия рабочей БД: типа `cell` там нет, резолвер выбирает «Ячейка …»
    с required_attrs, и создание падало 422 «Проверьте атрибуты объекта».
    При этом создание такого же объекта через реестр обязано требовать атрибуты.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    type_code = f"t_cell_{suffix.lower()}"
    created_type = client.post(
        "/api/asset-types",
        headers=admin_headers,
        json={
            "code": type_code,
            "name": f"Тестовая ячейка {suffix}",
            "category": "equipment",
            "required_attrs": ["power_kw"],
            "attr_schema": {"power_kw": {"type": "number"}},
        },
    )
    assert created_type.status_code == 201, created_type.text
    type_id = created_type.json()["id"]

    contour = _make_contour(client, admin_headers, "Контур с типом-ячейкой")
    try:
        response = client.post(
            f"/api/schema/assets/{contour['id']}/cells/bulk",
            headers=admin_headers,
            json={"count": 2, "start": 1, "prefix": "Яч. №", "type_code": type_code},
        )
        assert response.status_code == 201, response.text
        assert response.json()["count"] == 2

        # Правка ячейки (имя) не должна требовать паспортных атрибутов типа.
        cell_id = response.json()["items"][0]["id"]
        patched = client.patch(
            f"/api/assets/{cell_id}", headers=admin_headers, json={"name": "Яч. №1 (правка)"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "Яч. №1 (правка)"

        registry = client.post(
            "/api/assets",
            headers=admin_headers,
            json={"name": "Объект без атрибутов", "type_code": type_code},
        )
        assert registry.status_code == 422, registry.text
        assert "power_kw" in registry.json()["fields"]
    finally:
        for child in client.get(
            f"/api/assets/{contour['id']}/children", headers=admin_headers
        ).json():
            client.delete(
                f"/api/schema/assets/{contour['id']}/cells/{child['id']}", headers=admin_headers
            )
        client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)
        client.delete(f"/api/asset-types/{type_id}", headers=admin_headers)

def test_line_chain_between_cells_with_poles(client, admin_headers):
    """Линия между ячейками: N опор + связи цепочкой с общим line_id."""
    contour = _make_contour(client, admin_headers, "Контур для линии")
    try:
        first = client.post(
            f"/api/schema/assets/{contour['id']}/cells",
            headers=admin_headers,
            json={"label": "Яч. №7", "role": "outgoing"},
        ).json()
        second = client.post(
            f"/api/schema/assets/{contour['id']}/cells",
            headers=admin_headers,
            json={"label": "Яч. №6", "role": "incoming"},
        ).json()

        response = client.post(
            "/api/schema/lines/chain",
            headers=admin_headers,
            json={
                "from_asset_id": first["id"],
                "to_asset_id": second["id"],
                "poles": 3,
                "prefix": "Опора",
                "link_type": "overhead",
                "cable_mark": "АС-35",
                "line_name": "ВЛ-6 кВ тест",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["poles"]) == 3
        assert len(body["link_ids"]) == 4  # ячейка→3 опоры→ячейка

        lines = client.get("/api/lines", headers=admin_headers).json()
        assert any(line["id"] == body["line_id"] for line in lines)

        links = client.get(
            "/api/links", headers=admin_headers, params={"asset_id": first["id"]}
        ).json()["items"]
        assert any((link.get("line") or {}).get("id") == body["line_id"] for link in links)
        assert any(link["cable_mark"] == "АС-35" for link in links)
    finally:
        data = client.get(f"/api/assets/{contour['id']}/children", headers=admin_headers).json()
        for child in data:
            client.delete(
                f"/api/schema/assets/{contour['id']}/cells/{child['id']}", headers=admin_headers
            )
        client.delete(f"/api/assets/{contour['id']}", headers=admin_headers)