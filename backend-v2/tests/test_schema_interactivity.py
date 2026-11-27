"""Этап 3 «Продвинутая интерактивность схемы»: связи, размеры, координаты.

Контракт t3, который здесь закрепляется:

* ``POST /api/links`` принимает порты вложенных ячеек: внешний объект → ячейка
  БКРУ, ячейка → ячейка (``jumper`` внутри блока) и прежняя связь блок → блок —
  все 201; неизвестный порт → 404, порт архивного объекта → 422
  ``link.asset_archived``, порт объекта другого карьера → 404;
* ``PUT /api/topology/layout`` сохраняет размер блока (``gis.assets.
  schema_width/schema_height``) и координаты ячейки (``schema_local_x/y``), граф
  отдаёт их в ``blocks[]``/``blocks[].children[]``; координата вне
  ``0…width/height`` → 422 ``layout.out_of_bounds``; частично некорректный
  payload отклоняется целиком и раскладку не меняет;
* автосейв: серия из 12 последовательных PUT обновляет только переданные
  объекты, ``version``/``updated_at`` незатронутых объектов не меняются,
  ошибок и таймаутов нет;
* регресс этапа 2: on/off ячейки и install/return кабеля работают по-прежнему.

Тесты работают только на ``karier_test_db`` (см. ``tests/conftest.py``) и не
трогают seeded-данные: блоки/объекты создаются «с нуля» с уникальными кодами,
после теста их убирает ``isolate_created_rows``. «Чужой карьер» создаётся
напрямую в БД (неактивный pit) и удаляется в ``finally``.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import Asset, Link

PROBLEM_JSON = "application/problem+json"


# --- вспомогательные функции ------------------------------------------------


def _db_session():
    return SessionLocal()


def _unique(prefix: str) -> str:
    """Суффикс, уникальный между прогонами (тестовая БД живёт между запусками)."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _problem(response, status: int) -> dict:
    """Разобрать problem+json: статус, код и читаемый detail обязательны."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith(PROBLEM_JSON), response.headers["content-type"]
    body = response.json()
    assert body["status"] == status, body
    assert isinstance(body.get("code"), str) and body["code"], body
    assert isinstance(body.get("detail"), str) and body["detail"], body
    return body


def _compose(client, headers, type_code: str = "bkru", **extra) -> dict:
    """Создать составное устройство по шаблону типа (201 + тело ответа)."""
    suffix = uuid.uuid4().hex[:8].upper()
    payload = {
        "type_code": type_code,
        "name": f"QA3 {type_code} {suffix}",
        "code": f"QA3-{type_code.upper()}-{suffix}"[:64],
        "x": 320.0,
        "y": 180.0,
    }
    payload.update(extra)
    response = client.post("/api/schema/composite", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _asset_ports(client, headers, asset_id: str) -> dict[str, dict]:
    """Порты объекта из карточки ``GET /api/assets/{id}`` (ключ — код порта)."""
    response = client.get(f"/api/assets/{asset_id}", headers=headers)
    assert response.status_code == 200, response.text
    return {port["code"]: port for port in response.json()["ports"]}


def _asset_snapshot(asset_id: str) -> dict:
    """Слепок изменяемых этапом 3 полей: раскладка, размер, версия, updated_at."""
    db = _db_session()
    try:
        row = db.get(Asset, uuid.UUID(str(asset_id)))
        assert row is not None, f"объект {asset_id} не найден"
        return {
            "code": row.code,
            "status": row.status,
            "version": row.version,
            "updated_at": row.updated_at,
            "schema_width": float(row.schema_width) if row.schema_width is not None else None,
            "schema_height": float(row.schema_height) if row.schema_height is not None else None,
            "schema_local_x": (
                float(row.schema_local_x) if row.schema_local_x is not None else None
            ),
            "schema_local_y": (
                float(row.schema_local_y) if row.schema_local_y is not None else None
            ),
            "schema_x": float(row.schema_x) if row.schema_x is not None else None,
            "schema_y": float(row.schema_y) if row.schema_y is not None else None,
        }
    finally:
        db.close()


def _asset_id_by_code(code: str) -> uuid.UUID:
    db = _db_session()
    try:
        asset_id = db.scalar(text("select id from gis.assets where code = :code"), {"code": code})
        assert asset_id is not None, f"объект {code} не найден в тестовой БД"
        return asset_id
    finally:
        db.close()


def _link_row(link_id: str) -> dict:
    db = _db_session()
    try:
        row = db.get(Link, uuid.UUID(str(link_id)))
        assert row is not None, f"связь {link_id} не найдена"
        return {
            "from_port_id": str(row.from_port_id),
            "to_port_id": str(row.to_port_id),
            "cable_asset_id": str(row.cable_asset_id) if row.cable_asset_id else None,
            "cable_status": row.cable_status,
            "cable_mark": row.cable_mark,
            "state": row.state,
            "link_type": row.link_type,
            "version": row.version,
            "deleted_at": row.deleted_at,
        }
    finally:
        db.close()


def _graph_block(client, headers, block_id: str) -> tuple[dict, dict]:
    """Блок из ``GET /api/topology/graph`` и весь граф (для проверки рёбер)."""
    response = client.get("/api/topology/graph", headers=headers)
    assert response.status_code == 200, response.text
    graph = response.json()
    block = next(
        (item for item in graph["blocks"] if item["asset_id"] == block_id),
        None,
    )
    assert block is not None, f"блок {block_id} не попал в граф схемы"
    return block, graph


def _put_layout(client, headers, items: list[dict]):
    """PUT раскладки с замером времени: автосейв не должен «зависать»."""
    started = time.perf_counter()
    response = client.put(
        "/api/topology/layout",
        headers=headers,
        json={"items": items},
    )
    return response, time.perf_counter() - started


def _create_link(client, headers, from_port_id: str, to_port_id: str, **extra) -> dict:
    payload = {"from_port_id": from_port_id, "to_port_id": to_port_id}
    payload.update(extra)
    response = client.post("/api/links", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_external(client, headers, *, status: str = "on") -> dict:
    """Внешний объект (не блок и не ячейка) со своими портами IN-1/OUT-1."""
    response = client.post(
        "/api/assets",
        headers=headers,
        json={"name": _unique("QA3 внешний"), "type_code": "yaku", "status": status},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_cable(client, headers) -> dict:
    mark = f"QA3-Ф-{uuid.uuid4().hex[:6].upper()}"
    response = client.post(
        "/api/assets",
        headers=headers,
        json={
            "name": f"Кабель QA3 {mark}",
            "type_code": "cable",
            "lifecycle_status": "reserve",
            "attrs": {"cable_mark": mark, "length_m": 120.0, "section_mm2": 35.0},
        },
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    asset["_mark"] = mark
    return asset


def _create_foreign_port() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Порт объекта «чужого карьера»: неактивный pit + объект + порт.

    Публичный ``POST /api/links`` обязан ответить 404: порт есть в БД, но
    принадлежит другому карьеру (``pit_id`` не совпадает с активным).
    """
    db = _db_session()
    pit_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    port_id = uuid.uuid4()
    try:
        type_id = db.scalar(text("select id from gis.asset_types where code = 'yaku'"))
        assert type_id is not None, "тип yaku не найден в тестовой БД"
        db.execute(
            text(
                "insert into gis.pits (id, code, name, timezone, crs_name, is_active) "
                "values (:id, :code, :name, 'Asia/Irkutsk', 'Локальная СК карьера, м', false)"
            ),
            {"id": pit_id, "code": f"qa3-{uuid.uuid4().hex[:8]}", "name": "QA3 чужой карьер"},
        )
        db.execute(
            text(
                "insert into gis.assets "
                "(id, pit_id, asset_type_id, code, name, status, lifecycle, grounded, "
                " is_mobile, attrs, version) "
                "values (:id, :pit_id, :type_id, :code, :name, 'on', 'installed', false, "
                " false, '{}'::jsonb, 1)"
            ),
            {
                "id": asset_id,
                "pit_id": pit_id,
                "type_id": type_id,
                "code": f"QA3-FOREIGN-{uuid.uuid4().hex[:8].upper()}",
                "name": "QA3 объект чужого карьера",
            },
        )
        db.execute(
            text(
                "insert into gis.asset_ports "
                "(id, asset_id, code, name, kind, nominal_voltage_kv, sort_order) "
                "values (:id, :asset_id, 'OUT-1', 'Выход', 'out', 6.0, 0)"
            ),
            {"id": port_id, "asset_id": asset_id},
        )
        db.commit()
        return pit_id, asset_id, port_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _drop_foreign_port(pit_id: uuid.UUID, asset_id: uuid.UUID, port_id: uuid.UUID) -> None:
    """Убрать «чужой карьер» за тестом (идемпотентно)."""
    db = _db_session()
    try:
        db.execute(
            text(
                "delete from gis.links where from_port_id = :port or to_port_id = :port"
            ),
            {"port": port_id},
        )
        db.execute(text("delete from gis.asset_ports where id = :port"), {"port": port_id})
        db.execute(text("delete from gis.assets where id = :asset"), {"asset": asset_id})
        db.execute(text("delete from gis.pits where id = :pit"), {"pit": pit_id})
        db.commit()
    finally:
        db.close()


# --- 1. связи через порты вложенных ячеек ----------------------------------


def test_links_accept_ports_of_nested_cells(client, admin_headers):
    """Внешний объект → ячейка БКРУ, ячейка → ячейка и блок → блок — все 201."""
    block_a = _compose(client, admin_headers)
    block_b = _compose(client, admin_headers)
    external = _create_external(client, admin_headers)

    external_ports = _asset_ports(client, admin_headers, external["id"])
    block_a_ports = _asset_ports(client, admin_headers, block_a["id"])
    block_b_ports = _asset_ports(client, admin_headers, block_b["id"])
    cells = block_a["cells"]
    cell_in_ports = _asset_ports(client, admin_headers, cells[0]["id"])
    cell_out_ports = _asset_ports(client, admin_headers, cells[1]["id"])
    cell_target_ports = _asset_ports(client, admin_headers, cells[2]["id"])
    cell_b_ports = _asset_ports(client, admin_headers, block_b["cells"][0]["id"])

    # 1) внешний объект → ячейка БКРУ (порт вложенного объекта)
    external_to_cell = _create_link(
        client,
        admin_headers,
        external_ports["OUT-1"]["id"],
        cell_in_ports["IN-1"]["id"],
        link_type="cable",
        cable_mark="QA3-EXT-CELL",
    )
    assert external_to_cell["from_asset"]["id"] == external["id"]
    assert external_to_cell["to_asset"]["id"] == cells[0]["id"]
    assert external_to_cell["from_port"]["code"] == "OUT-1"
    assert external_to_cell["to_port"]["code"] == "IN-1"
    assert external_to_cell["link_type"] == "cable"
    assert external_to_cell["feed_role"] == "main"
    assert external_to_cell["state"] == "connected"
    assert external_to_cell["cable_mark"] == "QA3-EXT-CELL"

    # 2) ячейка → ячейка внутри одного БКРУ (jumper попадает в blocks[].jumpers)
    cell_to_cell = _create_link(
        client,
        admin_headers,
        cell_out_ports["OUT-1"]["id"],
        cell_target_ports["IN-1"]["id"],
        link_type="jumper",
        feed_role="backup",
    )
    assert cell_to_cell["from_asset"]["id"] == cells[1]["id"]
    assert cell_to_cell["to_asset"]["id"] == cells[2]["id"]
    assert cell_to_cell["link_type"] == "jumper"

    # 3) блок → блок по внешним портам: прежний сценарий не сломан
    block_to_block = _create_link(
        client,
        admin_headers,
        block_a_ports["OUT-1"]["id"],
        block_b_ports["IN-1"]["id"],
        link_type="cable",
    )
    assert block_to_block["from_asset"]["id"] == block_a["id"]
    assert block_to_block["to_asset"]["id"] == block_b["id"]
    assert block_to_block["from_port"]["code"] == "OUT-1"

    # В БД связи лежат ровно на тех портах, которые просили (вложенность не мешает).
    for created, from_port_id, to_port_id in (
        (external_to_cell, external_ports["OUT-1"]["id"], cell_in_ports["IN-1"]["id"]),
        (cell_to_cell, cell_out_ports["OUT-1"]["id"], cell_target_ports["IN-1"]["id"]),
        (block_to_block, block_a_ports["OUT-1"]["id"], block_b_ports["IN-1"]["id"]),
    ):
        row = _link_row(created["id"])
        assert row["from_port_id"] == from_port_id
        assert row["to_port_id"] == to_port_id
        assert row["deleted_at"] is None

    # Граф видит рёбра к вложенным ячейкам и блок → блок.
    graph_block_a, graph = _graph_block(client, admin_headers, block_a["id"])
    edges = {edge["id"]: edge for edge in graph["edges"]}
    assert {external_to_cell["id"], cell_to_cell["id"], block_to_block["id"]} <= set(edges)
    external_edge = edges[external_to_cell["id"]]
    assert external_edge["from_asset_id"] == external["id"]
    assert external_edge["to_asset_id"] == cells[0]["id"]
    block_edge = edges[block_to_block["id"]]
    assert block_edge["from_asset_id"] == block_a["id"]
    assert block_edge["to_asset_id"] == block_b["id"]

    child_ids = {child["id"] for child in graph_block_a["children"]}
    assert {cell["id"] for cell in cells} <= child_ids, "все ячейки БКРУ остаются внутри блока"
    jumpers = graph_block_a["jumpers"]
    assert any(
        jumper["from_cell_id"] == cells[1]["id"] and jumper["to_cell_id"] == cells[2]["id"]
        for jumper in jumpers
    ), jumpers


def test_links_reject_unknown_archived_and_foreign_ports(client, admin_headers):
    """Неизвестный порт/порт чужого карьера → 404, порт архивного объекта → 422."""
    block = _compose(client, admin_headers)
    cell = block["cells"][0]
    cell_ports = _asset_ports(client, admin_headers, cell["id"])

    # --- несуществующий порт (и во from_, и во to_) → 404 problem+json ---
    for payload in (
        {"from_port_id": str(uuid.uuid4()), "to_port_id": cell_ports["IN-1"]["id"]},
        {"from_port_id": cell_ports["OUT-1"]["id"], "to_port_id": str(uuid.uuid4())},
    ):
        response = client.post("/api/links", headers=admin_headers, json=payload)
        body = _problem(response, 404)
        assert body["code"] == "resource.not_found", body

    # --- порт объекта в архиве → 422 link.asset_archived ---
    archived = _create_external(client, admin_headers)
    archived_ports = _asset_ports(client, admin_headers, archived["id"])
    deleted = client.delete(f"/api/assets/{archived['id']}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text

    archived_link = client.post(
        "/api/links",
        headers=admin_headers,
        json={
            "from_port_id": archived_ports["OUT-1"]["id"],
            "to_port_id": cell_ports["IN-1"]["id"],
            "link_type": "cable",
        },
    )
    body = _problem(archived_link, 422)
    assert body["code"] == "link.asset_archived", body
    assert "архив" in body["detail"], body["detail"]

    # --- порт того же объекта, но другого карьера (pit_id не совпадает) → 404 ---
    pit_id, foreign_asset_id, foreign_port_id = _create_foreign_port()
    try:
        foreign_link = client.post(
            "/api/links",
            headers=admin_headers,
            json={
                "from_port_id": str(foreign_port_id),
                "to_port_id": cell_ports["IN-1"]["id"],
                "link_type": "cable",
            },
        )
        body = _problem(foreign_link, 404)
        assert body["code"] == "resource.not_found", body
    finally:
        _drop_foreign_port(pit_id, foreign_asset_id, foreign_port_id)

    # Ни одна из отклонённых попыток не оставила живой связи на порту ячейки.
    db = _db_session()
    try:
        alive = db.execute(
            text(
                "select count(*) from gis.links "
                "where deleted_at is null "
                "and (from_port_id = :to_port or to_port_id = :to_port)"
            ),
            {"to_port": uuid.UUID(cell_ports["IN-1"]["id"])},
        ).scalar_one()
    finally:
        db.close()
    assert alive == 0, "отклонённые связи не должны попадать в раскладку"


# --- 2. размеры блока и координаты ячеек ------------------------------------


def test_layout_block_size_saved_and_returned_by_graph(client, admin_headers):
    """PUT width/height → schema_width/schema_height в БД и в графе."""
    block = _compose(client, admin_headers)

    block_before, _ = _graph_block(client, admin_headers, block["id"])
    # новый блок этапа 2 размера не имеет: клиент рисует его своим дефолтом
    assert block_before["schema_width"] is None, block_before
    assert block_before["schema_height"] is None, block_before
    assert block_before["width"] is None and block_before["height"] is None, block_before
    children_before = {
        child["id"]: (child["local_x"], child["local_y"])
        for child in block_before["children"]
    }
    assert len(children_before) == len(block["cells"])

    response, elapsed = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "width": 520, "height": 360}],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["updated"] == 1, body
    assert body["updated_blocks"] == 1 and body["updated_cells"] == 0, body
    assert body["updated_ports"] == 0, body
    assert body["skipped"] == [], body
    assert elapsed < 5.0, f"PUT раскладки занял {elapsed:.2f} с"

    row = _asset_snapshot(block["id"])
    assert row["schema_width"] == 520.0, row
    assert row["schema_height"] == 360.0, row

    block_after, _ = _graph_block(client, admin_headers, block["id"])
    assert block_after["schema_width"] == 520.0, block_after
    assert block_after["schema_height"] == 360.0, block_after
    # исторические width/height — то же значение (совместимость со снимками/PDF)
    assert block_after["width"] == 520.0 and block_after["height"] == 360.0, block_after

    # Раскладка ячеек от ресайза не поехала: координаты не переданных объектов целы.
    children_after = {
        child["id"]: (child["local_x"], child["local_y"])
        for child in block_after["children"]
    }
    assert children_after == children_before, children_after

    # Карточка объекта тоже отдаёт размер (AssetOut этапа 3).
    detail = client.get(f"/api/assets/{block['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["schema_width"] == 520.0
    assert detail.json()["schema_height"] == 360.0


def test_layout_cell_local_coordinates_saved(client, admin_headers):
    """PUT local_x/local_y → schema_local_x/y в БД, графе и карточке объекта."""
    block = _compose(client, admin_headers)
    saved, elapsed = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "width": 480, "height": 320}],
    )
    assert saved.status_code == 200, saved.text
    assert elapsed < 5.0

    cell = block["cells"][1]
    response, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": cell["id"], "local_x": 180.5, "local_y": 120.25}],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["updated"] == 1, body
    assert body["updated_cells"] == 1 and body["updated_blocks"] == 0, body
    assert body["skipped"] == [], body

    row = _asset_snapshot(cell["id"])
    assert row["schema_local_x"] == 180.5, row
    assert row["schema_local_y"] == 120.25, row
    # размер блока не перепутан с координатами ячейки
    assert row["schema_width"] is None, row

    graph_block, _ = _graph_block(client, admin_headers, block["id"])
    child = next(item for item in graph_block["children"] if item["id"] == cell["id"])
    assert child["local_x"] == 180.5, child
    assert child["local_y"] == 120.25, child
    # координаты соседних ячеек не тронуты
    neighbour = next(
        item for item in graph_block["children"] if item["id"] == block["cells"][2]["id"]
    )
    assert (neighbour["local_x"], neighbour["local_y"]) == (300.0, 140.0), neighbour

    card = client.get(f"/api/assets/{cell['id']}", headers=admin_headers)
    assert card.status_code == 200, card.text
    assert card.json()["schema_local_x"] == 180.5
    assert card.json()["schema_local_y"] == 120.25

    # Граница блока включительно: local_x == width, local_y == height — 200.
    boundary, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": cell["id"], "local_x": 480, "local_y": 320}],
    )
    assert boundary.status_code == 200, boundary.text
    boundary_row = _asset_snapshot(cell["id"])
    assert boundary_row["schema_local_x"] == 480.0, boundary_row
    assert boundary_row["schema_local_y"] == 320.0, boundary_row

    # Ноль — тоже допустимая координата.
    origin, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": cell["id"], "local_x": 0, "local_y": 0}],
    )
    assert origin.status_code == 200, origin.text
    origin_row = _asset_snapshot(cell["id"])
    assert origin_row["schema_local_x"] == 0.0 and origin_row["schema_local_y"] == 0.0


def test_layout_rejects_bad_geometry_atomically(client, admin_headers):
    """422 на границы/минимумы/типы; частично некорректный payload не пишется."""
    block = _compose(client, admin_headers)
    first, second = block["cells"][0], block["cells"][1]
    sized, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "width": 480, "height": 300}],
    )
    assert sized.status_code == 200, sized.text

    baseline_block = _asset_snapshot(block["id"])
    baseline_first = _asset_snapshot(first["id"])
    baseline_second = _asset_snapshot(second["id"])
    assert (baseline_first["schema_local_x"], baseline_first["schema_local_y"]) == (60.0, 140.0)

    # X за правой границей блока (width=480) → 422 с указанием допустимого диапазона.
    too_far, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": first["id"], "local_x": 481, "local_y": 140}],
    )
    body = _problem(too_far, 422)
    assert body["code"] == "layout.out_of_bounds", body
    assert "480" in body["detail"], body["detail"]
    assert "480" in body.get("fields", {}).get("local_x", ""), body

    # Отрицательная координата → 422 (внутри блока отсчёт с нуля).
    negative, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": first["id"], "local_y": -1}],
    )
    body = _problem(negative, 422)
    assert body["code"] == "layout.out_of_bounds", body
    assert "отрицательная" in body["detail"], body["detail"]

    # Ни одна отклонённая запись не дошла до БД.
    assert _asset_snapshot(first["id"]) == baseline_first

    # Атомарность: первый элемент payload валиден, второй — нет → не меняется ничего.
    partial, _ = _put_layout(
        client,
        admin_headers,
        [
            {"asset_id": first["id"], "local_x": 10, "local_y": 10},
            {"asset_id": second["id"], "local_x": 99999, "local_y": 140},
        ],
    )
    body = _problem(partial, 422)
    assert body["code"] == "layout.out_of_bounds", body
    assert _asset_snapshot(first["id"]) == baseline_first, "валидный элемент не должен сохраниться"
    assert _asset_snapshot(second["id"]) == baseline_second
    assert _asset_snapshot(block["id"]) == baseline_block
    graph_block, _ = _graph_block(client, admin_headers, block["id"])
    graph_first = next(item for item in graph_block["children"] if item["id"] == first["id"])
    assert (graph_first["local_x"], graph_first["local_y"]) == (60.0, 140.0), graph_first

    # Минимумы размера блока: 120×80 px.
    too_small_w, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "width": 100, "height": 300}],
    )
    assert _problem(too_small_w, 422)["code"] == "layout.size_too_small"
    too_small_h, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "height": 50}],
    )
    assert _problem(too_small_h, 422)["code"] == "layout.size_too_small"
    too_large, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "width": 20000}],
    )
    assert _problem(too_large, 422)["code"] == "layout.size_too_large"

    # Размер — только у блока, локальные координаты — только у ячейки.
    width_on_cell, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": second["id"], "width": 200, "height": 200}],
    )
    assert _problem(width_on_cell, 422)["code"] == "layout.not_block"
    local_on_block, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "local_x": 10, "local_y": 10}],
    )
    assert _problem(local_on_block, 422)["code"] == "layout.not_cell"

    # После всех ошибок размер блока остался прежним (480×300), ячейки — на местах.
    final_block = _asset_snapshot(block["id"])
    assert final_block["schema_width"] == 480.0 and final_block["schema_height"] == 300.0
    assert final_block["updated_at"] == baseline_block["updated_at"]


def test_layout_autosave_series_touches_only_sent_assets(client, admin_headers):
    """12 последовательных PUT: меняется только цель, чужие версии/updated_at целы."""
    block = _compose(client, admin_headers)
    sized, _ = _put_layout(
        client,
        admin_headers,
        [{"asset_id": block["id"], "width": 640, "height": 480}],
    )
    assert sized.status_code == 200, sized.text

    target = block["cells"][0]
    # Контроль: сам блок, остальные ячейки и seeded-объект, который тест не трогает.
    control_ids = [block["id"]] + [cell["id"] for cell in block["cells"][1:]]
    control_ids.append(str(_asset_id_by_code("KTP-14")))
    controls_before = {asset_id: _asset_snapshot(asset_id) for asset_id in control_ids}
    target_before = _asset_snapshot(target["id"])

    latencies: list[float] = []
    for index in range(12):
        local_x = 40.0 + index * 5      # 40…95   (внутри width=640)
        local_y = 90.0 + index * 3      # 90…123  (внутри height=480)
        response, elapsed = _put_layout(
            client,
            admin_headers,
            [{"asset_id": target["id"], "local_x": local_x, "local_y": local_y}],
        )
        latencies.append(elapsed)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["updated"] == 1, body
        assert body["updated_cells"] == 1 and body["updated_blocks"] == 0, body
        assert body["skipped"] == [], body

    assert max(latencies) < 5.0, f"медленный PUT: {max(latencies):.2f} с"
    assert sum(latencies) < 30.0, f"серия PUT слишком долгая: {sum(latencies):.2f} с"

    # Цель получила последнее состояние серии.
    target_after = _asset_snapshot(target["id"])
    assert target_after["schema_local_x"] == 95.0, target_after
    assert target_after["schema_local_y"] == 123.0, target_after
    assert target_after["code"] == target_before["code"]

    # Незатронутые объекты не изменились вовсе: ни версия, ни updated_at, ни раскладка.
    for asset_id in control_ids:
        assert _asset_snapshot(asset_id) == controls_before[asset_id], asset_id

    graph_block, _ = _graph_block(client, admin_headers, block["id"])
    assert graph_block["schema_width"] == 640.0 and graph_block["schema_height"] == 480.0
    graph_target = next(
        child for child in graph_block["children"] if child["id"] == target["id"]
    )
    assert (graph_target["local_x"], graph_target["local_y"]) == (95.0, 123.0)


# --- 3. регресс этапа 2: переключение и кабельный учёт ----------------------


def test_toggle_and_cable_regression_after_stage3(client, admin_headers):
    """on/off ячейки и install/return кабеля не затронуты новым layout/links."""
    block = _compose(client, admin_headers)
    first, second = block["cells"][0], block["cells"][1]
    version_before = _asset_snapshot(first["id"])["version"]

    on = client.post(
        f"/api/assets/{first['id']}/toggle",
        headers=admin_headers,
        json={"state": "on", "reason": "QA3: регресс включения"},
    )
    assert on.status_code == 200, on.text
    on_body = on.json()
    assert on_body["status"] == "on" and on_body["previous_status"] == "off"
    assert on_body["changed"] is True
    assert on_body["energized"] is True and on_body["voltage_kv"] == 6.0
    after_on = _asset_snapshot(first["id"])
    assert after_on["status"] == "on"
    assert after_on["version"] == version_before + 1

    off = client.post(
        f"/api/assets/{first['id']}/toggle",
        headers=admin_headers,
        json={"state": "off", "reason": "QA3: регресс отключения"},
    )
    assert off.status_code == 200, off.text
    off_body = off.json()
    assert off_body["status"] == "off" and off_body["previous_status"] == "on"
    assert off_body["energized"] is False and off_body["voltage_kv"] == 0.0
    assert _asset_snapshot(first["id"])["status"] == "off"

    # --- кабельный учёт: install → return ---
    cable = _create_cable(client, admin_headers)
    cable_link = client.post(
        f"/api/schema/assets/{first['id']}/cables",
        headers=admin_headers,
        json={
            "to_asset_id": second["id"],
            "cable_mark": cable["_mark"],
            "length_m": 120.0,
            "cross_section_mm2": 35.0,
            "link_type": "cable",
        },
    )
    assert cable_link.status_code == 201, cable_link.text
    link = cable_link.json()
    assert _link_row(link["id"])["cable_asset_id"] is None

    installed = client.post(
        f"/api/cables/{cable['id']}/install",
        headers=admin_headers,
        json={"link_id": link["id"], "reason": "QA3: установка кабеля"},
    )
    assert installed.status_code == 200, installed.text
    installed_body = installed.json()
    assert installed_body["link_id"] == link["id"]
    assert installed_body["cable"]["lifecycle_status"] == "installed"
    link_after_install = _link_row(link["id"])
    assert link_after_install["cable_asset_id"] == cable["id"]
    assert link_after_install["cable_status"] == "in_work"
    assert link_after_install["cable_mark"] == cable["_mark"]

    returned = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "reserve", "reason": "QA3: снятие в запас"},
    )
    assert returned.status_code == 200, returned.text
    returned_body = returned.json()
    assert returned_body["detached_links"] == [link["id"]], returned_body
    assert returned_body["cable"]["lifecycle_status"] == "reserve"
    link_after_return = _link_row(link["id"])
    assert link_after_return["cable_asset_id"] is None
    assert link_after_return["cable_mark"] is None
    assert link_after_return["cable_status"] == "dismounted"

    # Связь не «потерялась»: остаётся живой, просто без кабеля.
    assert link_after_return["deleted_at"] is None
    assert link_after_return["state"] == "connected"
