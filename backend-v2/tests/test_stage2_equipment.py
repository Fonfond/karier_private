"""Этап 2 модели оборудования «Карьер»: шаблоны, переключение, кабельный учёт.

Контракт, который здесь закрепляется (t3):

* ``POST /api/schema/composite`` (admin) создаёт составное устройство одной
  транзакцией: БКРУ — ровно 6 ячеек с раскладкой
  ``in, out, out, sectional`` (секция 1) и ``out, in`` (секция 2), номера 1…6,
  ``section_no`` = 1,1,1,1,2,2; ПС 35/6 — 2 секции по 17 ячеек
  (1 ``in`` + 15 ``out`` + 1 ``sectional``), параметр ``cells_per_section``
  1…50 пересобирает секцию по формуле ``1 in + (n-2) out + 1 sectional``;
  КТП — 0 ячеек и один дочерний вводной разъединитель (``cell_kind=in``,
  тип класса ``switching``);
* ``POST /api/assets/{id}/toggle`` (право ``asset.status.edit``) переключает
  ячейку/разъединитель и возвращает ``status/energized/voltage_kv/grounded``;
  пишет ``audit.audit_log`` (``asset.toggled``: актор + прежнее/новое состояние)
  и ``gis.switching_ops``; без права — 403 ``perm.denied``; не-ячейка и
  не-коммутационный аппарат — 4xx ``asset.not_switchable``;
* кабельный учёт: ``GET /api/cables`` с фильтром ``installed|reserve|repair``,
  ``POST /api/cables/{id}/install`` заполняет ``links.cable_asset_id``,
  ``POST /api/cables/{id}/return`` снимает кабель в запас/ремонт; аудит
  ``cable.installed`` / ``cable.returned``; невалидный статус — 422.

Тесты работают только на ``karier_test_db`` (см. ``tests/conftest.py``): все
созданные объекты убирает ``isolate_created_rows``, seeded-данные не меняются.
Композитные блоки создаются «с нуля» под уникальным кодом, чтобы не зависеть
от остатков прошлых прогонов.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Asset, AuditLog, Employee, Link, Role, SwitchingOp

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


def _compose(client, headers, type_code: str, **extra) -> dict:
    """Создать составное устройство по шаблону типа (201 + тело ответа)."""
    suffix = uuid.uuid4().hex[:8].upper()
    payload = {
        "type_code": type_code,
        "name": f"QA {type_code} {suffix}",
        "code": f"QA-{type_code.upper()}-{suffix}"[:64],
        "x": 320.0,
        "y": 180.0,
    }
    payload.update(extra)
    response = client.post("/api/schema/composite", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _block_children(block_id: str) -> list[dict]:
    """Дочерние объекты блока из БД (порядок — по номеру ячейки)."""
    db = _db_session()
    try:
        rows = db.scalars(
            select(Asset)
            .where(Asset.schema_block_id == uuid.UUID(block_id), Asset.deleted_at.is_(None))
            .order_by(Asset.cell_no, Asset.code)
        ).unique().all()
        return [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "cell_kind": row.cell_kind,
                "cell_no": row.cell_no,
                "section_no": row.section_no,
                "schema_role": row.schema_role,
                "parent_id": str(row.parent_asset_id) if row.parent_asset_id else None,
                "schema_local_x": float(row.schema_local_x) if row.schema_local_x is not None else None,
                "schema_local_y": float(row.schema_local_y) if row.schema_local_y is not None else None,
                "status": row.status,
                "grounded": bool(row.grounded),
                "attrs": dict(row.attrs or {}),
                "type_code": row.asset_type.code if row.asset_type else None,
                "type_class": row.asset_type.equipment_class if row.asset_type else None,
            }
            for row in rows
        ]
    finally:
        db.close()


def _asset_row(asset_id: str) -> dict:
    """Текущее состояние объекта в БД (без ORM-связей, чтобы не зависеть от сессии)."""
    db = _db_session()
    try:
        row = db.get(Asset, uuid.UUID(str(asset_id)))
        assert row is not None, f"объект {asset_id} не найден"
        return {
            "status": row.status,
            "grounded": bool(row.grounded),
            "version": row.version,
            "lifecycle_status": row.lifecycle_status,
            "attrs": dict(row.attrs or {}),
            "cell_kind": row.cell_kind,
        }
    finally:
        db.close()


def _link_row(link_id: str) -> dict:
    db = _db_session()
    try:
        row = db.get(Link, uuid.UUID(str(link_id)))
        assert row is not None, f"связь {link_id} не найдена"
        return {
            "cable_asset_id": str(row.cable_asset_id) if row.cable_asset_id else None,
            "cable_status": row.cable_status,
            "state": row.state,
            "version": row.version,
            "cable_mark": row.cable_mark,
            "length_m": float(row.length_m) if row.length_m is not None else None,
            "cross_section_mm2": float(row.cross_section_mm2) if row.cross_section_mm2 is not None else None,
        }
    finally:
        db.close()


def _max_audit_id() -> int:
    db = _db_session()
    try:
        return db.scalar(select(func.max(AuditLog.id))) or 0
    finally:
        db.close()


def _audit_rows(action: str, entity_id: str, since_id: int = 0) -> list[AuditLog]:
    """Строки аудита по действию и объекту (append-only журнал)."""
    db = _db_session()
    try:
        return list(
            db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.action == action,
                    AuditLog.entity_id == str(entity_id),
                    AuditLog.id > since_id,
                )
                .order_by(AuditLog.id)
            ).all()
        )
    finally:
        db.close()


def _switching_ops(asset_id: str) -> list[dict]:
    """Записи журнала переключений по объекту (новые — в конце)."""
    db = _db_session()
    try:
        rows = db.scalars(
            select(SwitchingOp)
            .where(SwitchingOp.asset_id == uuid.UUID(str(asset_id)))
            .order_by(SwitchingOp.performed_at, SwitchingOp.action)
        ).all()
        return [
            {
                "action": row.action,
                "from_state": row.from_state,
                "to_state": row.to_state,
                "reason": row.reason,
                "performed_by": str(row.performed_by) if row.performed_by else None,
            }
            for row in rows
        ]
    finally:
        db.close()


def _admin_employee_id() -> uuid.UUID:
    db = _db_session()
    try:
        employee_id = db.scalar(select(Employee.id).where(Employee.tab_no == "000001"))
        assert employee_id is not None, "администратор 000001 не найден в тестовой БД"
        return employee_id
    finally:
        db.close()


def _role_headers(role_code: str) -> tuple[dict, uuid.UUID]:
    """Токен активного сотрудника с указанной ролью (без пароля/2FA)."""
    db = _db_session()
    try:
        role = db.scalar(select(Role).where(Role.code == role_code))
        assert role is not None, f"роль {role_code} не найдена"
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"Q{uuid.uuid4().hex[:8].upper()}",
            full_name=f"QA stage2 {role_code}",
            role_id=role.id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        token = create_access_token(str(employee.id), role=role_code, session_id=str(uuid.uuid4()))
        return {"Authorization": f"Bearer {token}"}, employee.id
    finally:
        db.close()


def _drop_employee(employee_id: uuid.UUID) -> None:
    db = _db_session()
    try:
        employee = db.get(Employee, employee_id)
        if employee is not None:
            db.delete(employee)
            db.commit()
    finally:
        db.close()


def _create_cable(client, headers, *, lifecycle_status: str = "reserve") -> dict:
    """Кабель-объект (тип класса cable) сразу в нужном состоянии учёта."""
    mark = f"Ф-{uuid.uuid4().hex[:6].upper()}"
    response = client.post(
        "/api/assets",
        headers=headers,
        json={
            "name": f"Кабель QA {mark}",
            "type_code": "cable",
            "lifecycle_status": lifecycle_status,
            "attrs": {"cable_mark": mark, "length_m": 120.0, "section_mm2": 35.0},
        },
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    asset["_mark"] = mark
    return asset


def _create_cable_link(client, headers, from_asset_id: str, to_asset_id: str, *, cable_mark: str) -> dict:
    """Кабельная связь между объектами (старый /api/schema/assets/{id}/cables)."""
    response = client.post(
        f"/api/schema/assets/{from_asset_id}/cables",
        headers=headers,
        json={
            "to_asset_id": to_asset_id,
            "cable_mark": cable_mark,
            "length_m": 120.0,
            "cross_section_mm2": 35.0,
            "link_type": "cable",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _cable_by_mark(client, headers, mark: str, lifecycle_status: str) -> dict | None:
    """Найти кабель в списке /api/cables по марке и состоянию учёта."""
    response = client.get(
        f"/api/cables?lifecycle_status={lifecycle_status}&q={mark}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()
    assert isinstance(items, list), items
    return next((item for item in items if mark in (item["name"] or "")), None)


# --- шаблоны составных устройств -------------------------------------------


def test_composite_bkru_exactly_six_cells_with_layout(client, admin_headers):
    """БКРУ: ровно 6 ячеек, фиксированная раскладка и две секции."""
    since = _max_audit_id()
    data = _compose(client, admin_headers, "bkru")

    assert data["type_code"] == "bkru"
    assert data["template_version"] == 2
    assert data["children"] == 6
    assert data["disconnector"] is None
    assert (data["schema_x"], data["schema_y"]) == (320.0, 180.0)
    assert data["block"]["id"] == data["id"]

    cells = data["cells"]
    assert len(cells) == 6
    assert [cell["cell_kind"] for cell in cells] == ["in", "out", "out", "sectional", "out", "in"]
    assert [cell["cell_no"] for cell in cells] == [1, 2, 3, 4, 5, 6]
    assert [cell["section_no"] for cell in cells] == [1, 1, 1, 1, 2, 2]
    assert [cell["status"] for cell in cells] == ["off"] * 6
    assert all(cell["grounded"] is False for cell in cells)
    assert all(cell["voltage_kv"] == 6.0 for cell in cells)
    # имена собираются из вида ячейки и сквозного номера
    assert [cell["name"] for cell in cells] == [
        "Яч. №1 (Вводная)",
        "Яч. №2 (Отходящая)",
        "Яч. №3 (Отходящая)",
        "Яч. №4 (Секционная)",
        "Яч. №5 (Отходящая)",
        "Яч. №6 (Вводная)",
    ]
    # сгруппированные секции: секция 1 — 4 ячейки, секция 2 — 2
    assert [section["section_no"] for section in data["sections"]] == [1, 2]
    assert [len(section["cells"]) for section in data["sections"]] == [4, 2]
    assert [section["label"] for section in data["sections"]] == ["Секция 1", "Секция 2"]
    assert [section["voltage_kv"] for section in data["sections"]] == [6.0, 6.0]

    # в БД: дети привязаны к блоку, роли схемы дублируют cell_kind
    children = _block_children(data["id"])
    assert [child["cell_kind"] for child in children] == ["in", "out", "out", "sectional", "out", "in"]
    assert [child["cell_no"] for child in children] == [1, 2, 3, 4, 5, 6]
    assert [child["section_no"] for child in children] == [1, 1, 1, 1, 2, 2]
    assert [child["schema_role"] for child in children] == [
        "incoming",
        "outgoing",
        "outgoing",
        "section",
        "outgoing",
        "incoming",
    ]
    assert all(child["parent_id"] == data["id"] for child in children)
    assert all(child["type_code"] == "cell" for child in children)
    # раскладка: 6 колонок в ряд (LAYOUT_COLUMNS=6), шаг 120×96, старт 60/140
    assert [child["schema_local_x"] for child in children] == [60.0, 180.0, 300.0, 420.0, 540.0, 660.0]
    assert [child["schema_local_y"] for child in children] == [140.0] * 6
    assert all(child["attrs"]["composite"] is True for child in children)

    # аудит создания: состав и число секций
    rows = _audit_rows("composite.composed", data["id"], since)
    assert len(rows) == 1, [row.detail for row in rows]
    recorded = rows[0]
    assert recorded.actor_tab_no == "000001"
    assert recorded.actor_id == _admin_employee_id()
    assert recorded.payload["type_code"] == "bkru"
    assert len(recorded.payload["cells"]) == 6
    assert recorded.payload["sections"] == 2
    assert recorded.payload["disconnector_id"] is None


def test_composite_ps_default_17_cells_per_section(client, admin_headers):
    """ПС 35/6: по умолчанию 2×17 ячеек, в каждой секции 1 in + 15 out + 1 sectional."""
    data = _compose(client, admin_headers, "substation")

    assert data["template_version"] == 2
    assert data["children"] == 34
    assert len(data["cells"]) == 34
    assert data["disconnector"] is None

    sections = data["sections"]
    assert [section["section_no"] for section in sections] == [1, 2]
    assert [section["label"] for section in sections] == ["Секция 1 (35 кВ)", "Секция 2 (6 кВ)"]
    assert [section["voltage_kv"] for section in sections] == [35.0, 6.0]

    for section in sections:
        kinds = [cell["cell_kind"] for cell in section["cells"]]
        assert len(kinds) == 17, kinds
        assert kinds.count("in") == 1
        assert kinds.count("out") == 15
        assert kinds.count("sectional") == 1
        # порядок шаблона: вводная → отходящие → секционная
        assert kinds[0] == "in"
        assert kinds[-1] == "sectional"
        assert all(cell["section_no"] == section["section_no"] for cell in section["cells"])
        assert all(cell["voltage_kv"] == section["voltage_kv"] for cell in section["cells"])

    # нумерация сквозная по блоку: 1…34
    assert [cell["cell_no"] for cell in data["cells"]] == list(range(1, 35))
    assert [cell["section_no"] for cell in data["cells"]] == [1] * 17 + [2] * 17
    assert len({cell["id"] for cell in data["cells"]}) == 34

    # параметр по умолчанию зафиксирован в атрибутах блока (для карточки и отчётов)
    block = client.get(f"/api/assets/{data['id']}", headers=admin_headers)
    assert block.status_code == 200, block.text
    assert block.json()["attrs"]["cells_per_section"] == 17
    assert block.json()["attrs"]["template_version"] == 2

    children = _block_children(data["id"])
    assert len(children) == 34
    assert all(child["parent_id"] == data["id"] for child in children)


def test_composite_ps_cells_per_section_parameter(client, admin_headers):
    """Параметр cells_per_section пересобирает секцию: 1 in + (n−2) out + 1 sectional.

    Семантика зафиксирована в контракте t1 (§4.1): ``cells_per_section`` — число
    ячеек **всей секции**, поэтому по умолчанию 17 = 1 in + 15 out + 1 sectional.
    Для n=3 секция = 1 in + 1 out + 1 sectional (3 ячейки); «3 отходящих +
    2 служебных» получаются при n=5 — оба случая проверяются ниже.
    """
    three = _compose(client, admin_headers, "substation", cells_per_section=3)
    assert three["children"] == 6
    assert len(three["sections"]) == 2
    for section in three["sections"]:
        assert [cell["cell_kind"] for cell in section["cells"]] == ["in", "out", "sectional"]
        assert section["voltage_kv"] in (35.0, 6.0)
    assert [cell["cell_no"] for cell in three["cells"]] == [1, 2, 3, 4, 5, 6]
    block = client.get(f"/api/assets/{three['id']}", headers=admin_headers).json()
    assert block["attrs"]["cells_per_section"] == 3

    five = _compose(client, admin_headers, "substation", cells_per_section=5)
    assert five["children"] == 10
    for section in five["sections"]:
        kinds = [cell["cell_kind"] for cell in section["cells"]]
        assert len(kinds) == 5
        assert kinds.count("out") == 3  # 3 отходящих
        assert kinds.count("in") + kinds.count("sectional") == 2  # 2 служебных
        assert kinds == ["in"] + ["out"] * 3 + ["sectional"]

    ten = _compose(client, admin_headers, "substation", cells_per_section=10)
    assert ten["children"] == 20
    assert len(ten["sections"][0]["cells"]) == 10
    assert len(ten["sections"][1]["cells"]) == 10


def test_composite_invalid_cells_per_section_rejected(client, admin_headers):
    """Недопустимые значения параметра и настройка неконфигурируемого шаблона — 422."""
    invalid_names: list[str] = []
    for value in (0, 51, -1):
        name = _unique(f"QA ПС невалид {value}")
        invalid_names.append(name)
        response = client.post(
            "/api/schema/composite",
            headers=admin_headers,
            json={
                "type_code": "substation",
                "name": name,
                "code": _unique("QA-BAD-PS"),
                "x": 10.0,
                "y": 10.0,
                "cells_per_section": value,
            },
        )
        body = _problem(response, 422)
        assert body["code"] == "validation.failed", body
        assert "cells_per_section" in body.get("fields", {}), body

    # ни один «полублок» не создан: составное устройство создаётся одной транзакцией
    db = _db_session()
    try:
        leftovers = db.scalars(select(Asset).where(Asset.name.in_(invalid_names))).all()
        assert leftovers == [], [asset.name for asset in leftovers]
    finally:
        db.close()

    # БКРУ и КТП — фиксированный состав: параметр запрещён отдельным кодом ошибки
    for type_code in ("bkru", "ktp"):
        response = client.post(
            "/api/schema/composite",
            headers=admin_headers,
            json={
                "type_code": type_code,
                "name": _unique(f"QA {type_code} configurable"),
                "code": _unique(f"QA-{type_code.upper()}-CFG"),
                "x": 10.0,
                "y": 10.0,
                "cells_per_section": 3,
            },
        )
        body = _problem(response, 422)
        assert body["code"] == "composite.not_configurable", body


def test_composite_ktp_has_no_cells_but_toggleable_disconnector(client, admin_headers):
    """КТП: 0 ячеек, один дочерний вводной разъединитель; он переключается."""
    since = _max_audit_id()
    data = _compose(client, admin_headers, "ktp")

    assert data["children"] == 1
    assert data["cells"] == []
    assert data["sections"] == []
    assert data["template_version"] == 2
    disconnector = data["disconnector"]
    assert disconnector is not None, data
    assert data["disconnector_id"] == disconnector["id"]
    assert disconnector["cell_kind"] == "in"
    assert disconnector["type_code"] == "razedinitel"
    assert disconnector["name"] == "Вводной разъединитель"
    assert disconnector["status"] == "off"
    assert disconnector["grounded"] is False

    # в БД: дочерний объект блока, тип класса switching, напряжение 6 кВ в attrs
    children = _block_children(data["id"])
    assert len(children) == 1
    child = children[0]
    assert child["id"] == disconnector["id"]
    assert child["parent_id"] == data["id"]
    assert child["cell_kind"] == "in"
    assert child["type_code"] == "razedinitel"
    assert child["type_class"] == "switching"
    assert child["schema_role"] == "incoming"
    assert child["attrs"]["role"] == "disconnector"
    assert child["attrs"]["voltage_kv"] == 6.0

    # аудит создания: блок без ячеек, но с разъединителем
    rows = _audit_rows("composite.composed", data["id"], since)
    assert len(rows) == 1
    assert rows[0].payload["cells"] == []
    assert rows[0].payload["disconnector_id"] == disconnector["id"]

    # переключение разъединителя — та же кнопка/точка API, что у ячеек
    turned_on = client.post(
        f"/api/assets/{disconnector['id']}/toggle", headers=admin_headers, json={"state": "on"}
    )
    assert turned_on.status_code == 200, turned_on.text
    body = turned_on.json()
    assert body["status"] == "on"
    assert body["previous_status"] == "off"
    assert body["cell_kind"] == "in"
    assert body["changed"] is True
    assert body["energized"] is True
    assert body["voltage_kv"] == 6.0
    assert body["grounded"] is False

    turned_off = client.post(
        f"/api/assets/{disconnector['id']}/toggle", headers=admin_headers, json={"state": "off"}
    )
    assert turned_off.status_code == 200, turned_off.text
    assert turned_off.json()["status"] == "off"
    assert turned_off.json()["energized"] is False
    assert turned_off.json()["voltage_kv"] == 0.0
    assert turned_off.json()["nominal_voltage_kv"] == 6.0


# --- переключение ячейки и разъединителя ------------------------------------


def test_toggle_cell_returns_status_energized_voltage(client, admin_headers):
    """on/off ячейки: status/energized/voltage_kv/grounded в ответе и в БД."""
    block = _compose(client, admin_headers, "bkru")
    cell = block["cells"][0]
    assert cell["cell_kind"] == "in"
    before = _asset_row(cell["id"])
    assert before["status"] == "off"

    on = client.post(
        f"/api/assets/{cell['id']}/toggle", headers=admin_headers, json={"state": "on"}
    )
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["asset_id"] == cell["id"]
    assert body["code"] == cell["code"]
    assert body["name"] == cell["name"]
    assert body["cell_kind"] == "in"
    assert body["status"] == "on"
    assert body["previous_status"] == "off"
    assert body["changed"] is True
    assert body["grounded"] is False
    assert body["energized"] is True
    assert body["voltage_kv"] == 6.0
    assert body["nominal_voltage_kv"] == 6.0
    # графовая достижимость не обязана быть True: ячейка ещё не подключена связями
    assert body["topology_energized"] in (True, False)

    after_on = _asset_row(cell["id"])
    assert after_on["status"] == "on"
    assert after_on["version"] == before["version"] + 1
    # карточка объекта показывает то же состояние
    card = client.get(f"/api/assets/{cell['id']}", headers=admin_headers)
    assert card.status_code == 200
    assert card.json()["status"] == "on"

    off = client.post(
        f"/api/assets/{cell['id']}/toggle", headers=admin_headers, json={"state": "off"}
    )
    assert off.status_code == 200, off.text
    body = off.json()
    assert body["status"] == "off"
    assert body["previous_status"] == "on"
    assert body["changed"] is True
    assert body["energized"] is False
    assert body["voltage_kv"] == 0.0
    assert body["nominal_voltage_kv"] == 6.0
    assert _asset_row(cell["id"])["status"] == "off"

    # повтор того же состояния — не ошибка, но changed=false (кнопка не «дёргается»)
    again = client.post(
        f"/api/assets/{cell['id']}/toggle", headers=admin_headers, json={"state": "off"}
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "off"
    assert again.json()["changed"] is False

    # без тела — «переключить»: off → on
    without_body = client.post(f"/api/assets/{cell['id']}/toggle", headers=admin_headers)
    assert without_body.status_code == 200, without_body.text
    assert without_body.json()["status"] == "on"
    assert without_body.json()["previous_status"] == "off"
    assert without_body.json()["energized"] is True


def test_toggle_grounded_cell_is_not_energized(client, admin_headers):
    """Заземлённая ячейка: зелёный цвет (energized=false) даже при status=on."""
    block = _compose(client, admin_headers, "bkru")
    cell = block["cells"][1]

    grounded = client.post(
        f"/api/assets/{cell['id']}/state",
        headers=admin_headers,
        json={"grounded": True, "reason": "QA: работы на линии"},
    )
    assert grounded.status_code == 200, grounded.text
    assert grounded.json()["asset"]["grounded"] is True

    on = client.post(
        f"/api/assets/{cell['id']}/toggle", headers=admin_headers, json={"state": "on"}
    )
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["status"] == "on"
    assert body["grounded"] is True
    assert body["energized"] is False
    assert body["voltage_kv"] == 0.0
    assert body["nominal_voltage_kv"] == 6.0


def test_toggle_writes_audit_with_actor_and_previous_new_state(client, admin_headers):
    """Аудит переключения: актор, прежнее/новое состояние, причина, журнал операций."""
    block = _compose(client, admin_headers, "bkru")
    cell = block["cells"][0]
    admin_id = _admin_employee_id()
    since = _max_audit_id()

    reason = "QA: включение вводной ячейки"
    response = client.post(
        f"/api/assets/{cell['id']}/toggle",
        headers=admin_headers,
        json={"state": "on", "reason": reason},
    )
    assert response.status_code == 200, response.text

    rows = _audit_rows("asset.toggled", cell["id"], since)
    assert len(rows) == 1, [row.detail for row in rows]
    row = rows[0]
    assert row.entity == "asset"
    assert row.actor_id == admin_id
    assert row.actor_tab_no == "000001"
    assert row.actor_role == "admin"
    assert row.result == "ok"
    assert row.detail.startswith(cell["code"])
    assert "off → on" in row.detail
    payload = row.payload
    assert payload["from_state"] == "off"
    assert payload["to_state"] == "on"
    # алиасы для читаемости журнала
    assert payload["from"] == "off"
    assert payload["to"] == "on"
    assert payload["reason"] == reason
    assert payload["energized"] is True
    assert payload["voltage_kv"] == 6.0
    assert payload["grounded"] is False
    assert payload["cell_kind"] == "in"
    assert payload["changed"] is True

    operations = _switching_ops(cell["id"])
    assert len(operations) == 1, operations
    assert operations[0]["action"] == "status_on"
    assert operations[0]["from_state"] == "off"
    assert operations[0]["to_state"] == "on"
    assert operations[0]["reason"] == reason
    assert operations[0]["performed_by"] == str(admin_id)

    # обратное переключение пишет вторую строку с новыми from/to
    since_off = _max_audit_id()
    off = client.post(
        f"/api/assets/{cell['id']}/toggle", headers=admin_headers, json={"state": "off"}
    )
    assert off.status_code == 200, off.text
    rows_off = _audit_rows("asset.toggled", cell["id"], since_off)
    assert len(rows_off) == 1
    assert rows_off[0].payload["from_state"] == "on"
    assert rows_off[0].payload["to_state"] == "off"
    assert rows_off[0].payload["energized"] is False
    assert "on → off" in rows_off[0].detail


def test_toggle_requires_asset_status_edit_permission(client, admin_headers):
    """Без права asset.status.edit — 403 и объект не меняется; у оператора право есть."""
    block = _compose(client, admin_headers, "bkru")
    cell = block["cells"][0]

    viewer_headers, viewer_id = _role_headers("viewer")
    try:
        denied = client.post(
            f"/api/assets/{cell['id']}/toggle", headers=viewer_headers, json={"state": "on"}
        )
        body = _problem(denied, 403)
        assert body["code"] == "perm.denied", body
        assert _asset_row(cell["id"])["status"] == "off"
        # отказ тоже попадает в аудит — с актором
        denied_rows = _audit_rows("perm.denied", "asset.status.edit")
        assert any(
            row.result == "denied" and row.actor_id == viewer_id for row in denied_rows
        ), [(row.result, row.actor_id) for row in denied_rows]
    finally:
        _drop_employee(viewer_id)

    operator_headers, operator_id = _role_headers("operator")
    try:
        allowed = client.post(
            f"/api/assets/{cell['id']}/toggle", headers=operator_headers, json={"state": "on"}
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["status"] == "on"
        assert _asset_row(cell["id"])["status"] == "on"
        assert any(
            row.actor_id == operator_id and row.action == "asset.toggled"
            for row in _audit_rows("asset.toggled", cell["id"])
        )
    finally:
        _drop_employee(operator_id)


def test_toggle_rejects_asset_that_is_not_cell_or_switching(client, admin_headers):
    """Не-ячейка/не-разъединитель переключать нельзя: 4xx + объект не меняется.

    Контракт t1 (§4.2) и реализация отдают 422 ``asset.not_switchable``
    (422 Unprocessable Entity — тот же класс клиентской ошибки, что и «400» из
    формулировки t3; менять код вне зоны тестового этапа нельзя).
    """
    pole_name = _unique("QA Опора")
    created = client.post(
        "/api/assets",
        headers=admin_headers,
        json={"name": pole_name, "type_code": "pole", "status": "on"},
    )
    assert created.status_code == 201, created.text
    pole = created.json()

    response = client.post(
        f"/api/assets/{pole['id']}/toggle", headers=admin_headers, json={"state": "off"}
    )
    body = _problem(response, 422)
    assert body["code"] == "asset.not_switchable", body
    assert _asset_row(pole["id"])["status"] == "on"

    # комплектный блок (сам КТП) тоже не коммутационный аппарат
    ktp = _compose(client, admin_headers, "ktp")
    block_response = client.post(
        f"/api/assets/{ktp['id']}/toggle", headers=admin_headers, json={"state": "off"}
    )
    body = _problem(block_response, 422)
    assert body["code"] == "asset.not_switchable", body

    # несуществующий объект — 404
    missing = client.post(
        f"/api/assets/{uuid.uuid4()}/toggle", headers=admin_headers, json={"state": "on"}
    )
    assert _problem(missing, 404)["code"] == "resource.not_found"

    # недопустимое состояние — 422 problem+json (а не 500)
    cell = _compose(client, admin_headers, "bkru")["cells"][2]
    bad_state = client.post(
        f"/api/assets/{cell['id']}/toggle", headers=admin_headers, json={"state": "standby"}
    )
    body = _problem(bad_state, 422)
    assert body["code"] == "validation.failed", body
    assert "state" in body.get("fields", {}), body


# --- кабельный учёт ---------------------------------------------------------


def test_cable_install_return_reserve_and_repair(client, admin_headers):
    """install → links.cable_asset_id + installed; return → reserve/repair; аудит."""
    block = _compose(client, admin_headers, "bkru")
    first, second, third = block["cells"][0], block["cells"][1], block["cells"][2]
    cable = _create_cable(client, admin_headers, lifecycle_status="reserve")
    link = _create_cable_link(
        client, admin_headers, first["id"], second["id"], cable_mark=cable["_mark"]
    )
    assert _link_row(link["id"])["cable_asset_id"] is None

    # кабель в запасе виден в списке запаса
    assert _cable_by_mark(client, admin_headers, cable["_mark"], "reserve") is not None

    since_install = _max_audit_id()
    installed = client.post(
        f"/api/cables/{cable['id']}/install",
        headers=admin_headers,
        json={"link_id": link["id"], "reason": "QA: установка на линию"},
    )
    assert installed.status_code == 200, installed.text
    body = installed.json()
    assert body["link_id"] == link["id"]
    assert body["link_label"]
    assert body["cable"]["id"] == cable["id"]
    assert body["cable"]["lifecycle_status"] == "installed"
    assert body["cable"]["link_id"] == link["id"]
    assert body["cable"]["link_state"] == "connected"
    assert body["cable"]["from_asset"]["id"] == first["id"]
    assert body["cable"]["to_asset"]["id"] == second["id"]
    assert body["cable"]["cable_mark"] == cable["_mark"]

    link_row = _link_row(link["id"])
    assert link_row["cable_asset_id"] == cable["id"]
    assert link_row["cable_status"] == "in_work"
    assert link_row["cable_mark"] == cable["_mark"]
    assert link_row["length_m"] == 120.0
    assert link_row["cross_section_mm2"] == 35.0
    cable_row = _asset_row(cable["id"])
    assert cable_row["lifecycle_status"] == "installed"
    assert cable_row["attrs"]["installed_link_id"] == link["id"]

    listing = client.get("/api/cables?lifecycle_status=installed", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    installed_item = next(item for item in listing.json() if item["id"] == cable["id"])
    assert installed_item["lifecycle_status"] == "installed"
    assert installed_item["link_id"] == link["id"]
    assert installed_item["cable_mark"] == cable["_mark"]

    install_audit = _audit_rows("cable.installed", cable["id"], since_install)
    assert len(install_audit) == 1, [row.detail for row in install_audit]
    assert install_audit[0].actor_tab_no == "000001"
    assert install_audit[0].actor_id == _admin_employee_id()
    payload = install_audit[0].payload
    assert payload["from_status"] == "reserve"
    assert payload["to_status"] == "installed"
    assert payload["link_id"] == link["id"]
    assert payload["asset_id"] is None
    assert payload["reason"] == "QA: установка на линию"

    # --- снятие в запас ---
    since_return = _max_audit_id()
    returned = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "reserve", "reason": "QA: снятие в запас"},
    )
    assert returned.status_code == 200, returned.text
    returned_body = returned.json()
    assert returned_body["cable"]["lifecycle_status"] == "reserve"
    assert returned_body["detached_links"] == [link["id"]]
    # F4: связь больше не хранит параметры снятого кабеля — все четыре поля очищены
    cleared_row = _link_row(link["id"])
    assert cleared_row["cable_asset_id"] is None
    assert cleared_row["cable_mark"] is None
    assert cleared_row["length_m"] is None
    assert cleared_row["cross_section_mm2"] is None
    assert cleared_row["cable_status"] == "dismounted"
    assert _asset_row(cable["id"])["lifecycle_status"] == "reserve"
    assert _cable_by_mark(client, admin_headers, cable["_mark"], "reserve") is not None

    return_audit = _audit_rows("cable.returned", cable["id"], since_return)
    assert len(return_audit) == 1, [row.detail for row in return_audit]
    assert return_audit[0].payload["from_status"] == "installed"
    assert return_audit[0].payload["to_status"] == "reserve"
    assert return_audit[0].payload["links"] == [link["id"]]
    assert return_audit[0].payload["reason"] == "QA: снятие в запас"

    # --- повторная установка и снятие в ремонт ---
    reinstalled = client.post(
        f"/api/cables/{cable['id']}/install",
        headers=admin_headers,
        json={"link_id": link["id"]},
    )
    assert reinstalled.status_code == 200, reinstalled.text
    assert reinstalled.json()["cable"]["lifecycle_status"] == "installed"
    # F4: повторная установка снова заполняет денормализацию из карточки кабеля
    restored_row = _link_row(link["id"])
    assert restored_row["cable_asset_id"] == cable["id"]
    assert restored_row["cable_mark"] == cable["_mark"]
    assert restored_row["length_m"] == 120.0
    assert restored_row["cross_section_mm2"] == 35.0
    assert restored_row["cable_status"] == "in_work"

    repaired = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "repair", "reason": "QA: повреждение изоляции"},
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["cable"]["lifecycle_status"] == "repair"
    assert repaired.json()["detached_links"] == [link["id"]]
    assert _asset_row(cable["id"])["lifecycle_status"] == "repair"
    repaired_row = _link_row(link["id"])
    assert repaired_row["cable_asset_id"] is None
    assert repaired_row["cable_mark"] is None
    assert repaired_row["length_m"] is None
    assert repaired_row["cross_section_mm2"] is None
    assert _cable_by_mark(client, admin_headers, cable["_mark"], "repair") is not None

    repair_audit = _audit_rows("cable.returned", cable["id"], since_return)
    assert [row.payload["to_status"] for row in repair_audit] == ["reserve", "repair"]

    # --- установка «на объект» (без свободной связи): числится на объекте ---
    installed_on_asset = client.post(
        f"/api/cables/{cable['id']}/install",
        headers=admin_headers,
        json={"asset_id": third["id"], "reason": "QA: установка на объект"},
    )
    assert installed_on_asset.status_code == 200, installed_on_asset.text
    on_asset_body = installed_on_asset.json()
    assert on_asset_body["link_id"] is None
    assert on_asset_body["cable"]["lifecycle_status"] == "installed"
    assert on_asset_body["cable"]["installed_on"] == third["code"]
    cable_row = _asset_row(cable["id"])
    assert cable_row["attrs"]["installed_on_asset_id"] == third["id"]


def test_cable_return_clears_denormalization_and_audit(client, admin_headers):
    """F4: возврат очищает cable_asset_id/cable_mark/length_m/cross_section_mm2.

    Проверяем полный цикл: install заполняет четыре поля → return в запас очищает
    их (cable_status='dismounted', кабель — reserve) → повторный return
    идемпотентен (200, detached_links=[], аудит с пустым cleared) → повторная
    установка снова заполняет поля → return {"status":"installed"} — это
    подтверждение установки, связь и денормализация сохраняются → return в
    ремонт снова очищает. Аудит ``cable.returned`` фиксирует ``cleared_fields``
    и прежние значения в ``cleared``.
    """
    block = _compose(client, admin_headers, "bkru")
    first, second = block["cells"][0], block["cells"][1]
    cable = _create_cable(client, admin_headers, lifecycle_status="reserve")
    link = _create_cable_link(
        client, admin_headers, first["id"], second["id"], cable_mark=cable["_mark"]
    )

    installed = client.post(
        f"/api/cables/{cable['id']}/install",
        headers=admin_headers,
        json={"link_id": link["id"], "reason": "F4: установка"},
    )
    assert installed.status_code == 200, installed.text
    filled = _link_row(link["id"])
    assert filled["cable_asset_id"] == cable["id"]
    assert filled["cable_mark"] == cable["_mark"]
    assert filled["length_m"] == 120.0
    assert filled["cross_section_mm2"] == 35.0
    assert filled["cable_status"] == "in_work"

    # --- return в запас: очистка четырёх полей + аудит с прежними значениями ---
    since_return = _max_audit_id()
    returned = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "reserve", "reason": "F4: снятие в запас"},
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["detached_links"] == [link["id"]]
    assert returned.json()["cable"]["lifecycle_status"] == "reserve"
    cleared = _link_row(link["id"])
    assert cleared["cable_asset_id"] is None
    assert cleared["cable_mark"] is None
    assert cleared["length_m"] is None
    assert cleared["cross_section_mm2"] is None
    assert cleared["cable_status"] == "dismounted"
    assert _asset_row(cable["id"])["lifecycle_status"] == "reserve"
    version_after_first_return = cleared["version"]

    return_audit = _audit_rows("cable.returned", cable["id"], since_return)
    assert len(return_audit) == 1, [row.detail for row in return_audit]
    row = return_audit[0]
    assert row.actor_tab_no == "000001"
    assert row.actor_id == _admin_employee_id()
    payload = row.payload
    assert payload["from_status"] == "installed"
    assert payload["to_status"] == "reserve"
    assert payload["links"] == [link["id"]]
    assert payload["reason"] == "F4: снятие в запас"
    assert payload["cleared_fields"] == [
        "cable_asset_id",
        "cable_mark",
        "length_m",
        "cross_section_mm2",
    ]
    assert len(payload["cleared"]) == 1
    previous = payload["cleared"][0]
    assert previous["link_id"] == link["id"]
    assert previous["cable_asset_id"] == cable["id"]
    assert previous["cable_mark"] == cable["_mark"]
    assert previous["length_m"] == 120.0
    assert previous["cross_section_mm2"] == 35.0
    assert "очищены cable_mark/length_m/cross_section_mm2" in row.detail

    # --- повторный return идемпотентен: связей нет, аудит не врёт про очистку ---
    since_repeat = _max_audit_id()
    repeated = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "reserve", "reason": "F4: повторное снятие"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["detached_links"] == []
    assert repeated.json()["cable"]["lifecycle_status"] == "reserve"
    again = _link_row(link["id"])
    assert again["cable_asset_id"] is None
    assert again["cable_mark"] is None
    assert again["length_m"] is None
    assert again["cross_section_mm2"] is None
    assert again["version"] == version_after_first_return  # связь не трогали
    repeat_audit = _audit_rows("cable.returned", cable["id"], since_repeat)
    assert len(repeat_audit) == 1
    repeat_payload = repeat_audit[0].payload
    assert repeat_payload["from_status"] == "reserve"
    assert repeat_payload["to_status"] == "reserve"
    assert repeat_payload["links"] == []
    assert repeat_payload["cleared_fields"] == []
    assert repeat_payload["cleared"] == []

    # --- повторная установка снова заполняет денормализацию ---
    reinstalled = client.post(
        f"/api/cables/{cable['id']}/install",
        headers=admin_headers,
        json={"link_id": link["id"], "reason": "F4: повторная установка"},
    )
    assert reinstalled.status_code == 200, reinstalled.text
    restored = _link_row(link["id"])
    assert restored["cable_asset_id"] == cable["id"]
    assert restored["cable_mark"] == cable["_mark"]
    assert restored["length_m"] == 120.0
    assert restored["cross_section_mm2"] == 35.0
    assert restored["cable_status"] == "in_work"

    # --- return {"status":"installed"} — подтверждение, а не снятие ---
    since_confirm = _max_audit_id()
    confirmed = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "installed", "reason": "F4: подтверждение"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["detached_links"] == []
    assert confirmed.json()["cable"]["lifecycle_status"] == "installed"
    kept = _link_row(link["id"])
    assert kept["cable_asset_id"] == cable["id"]
    assert kept["cable_mark"] == cable["_mark"]
    assert kept["length_m"] == 120.0
    assert kept["cross_section_mm2"] == 35.0
    assert kept["cable_status"] == "in_work"
    confirm_audit = _audit_rows("cable.returned", cable["id"], since_confirm)
    assert len(confirm_audit) == 1
    assert confirm_audit[0].payload["to_status"] == "installed"
    assert confirm_audit[0].payload["links"] == []
    assert confirm_audit[0].payload["cleared_fields"] == []

    # --- return в ремонт снова очищает поля ---
    since_repair = _max_audit_id()
    repaired = client.post(
        f"/api/cables/{cable['id']}/return",
        headers=admin_headers,
        json={"status": "repair", "reason": "F4: в ремонт"},
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["cable"]["lifecycle_status"] == "repair"
    assert repaired.json()["detached_links"] == [link["id"]]
    final = _link_row(link["id"])
    assert final["cable_asset_id"] is None
    assert final["cable_mark"] is None
    assert final["length_m"] is None
    assert final["cross_section_mm2"] is None
    assert final["cable_status"] == "dismounted"
    repair_audit = _audit_rows("cable.returned", cable["id"], since_repair)
    assert len(repair_audit) == 1
    assert repair_audit[0].payload["to_status"] == "repair"
    assert repair_audit[0].payload["cleared_fields"] == [
        "cable_asset_id",
        "cable_mark",
        "length_m",
        "cross_section_mm2",
    ]
    assert repair_audit[0].payload["cleared"][0]["cable_mark"] == cable["_mark"]


def test_cable_invalid_statuses_and_install_conflicts(client, admin_headers):
    """Невалидные статусы — 422; конфликты установки — 409; не-кабель — 422."""
    # невалидный фильтр списка кабелей
    filtered = client.get("/api/cables?lifecycle_status=bogus", headers=admin_headers)
    body = _problem(filtered, 422)
    assert body["code"] == "validation.failed", body
    # ключ поля у query-параметра приходит с префиксом loc: query.lifecycle_status
    assert any(key.endswith("lifecycle_status") for key in body.get("fields", {})), body

    block = _compose(client, admin_headers, "bkru")
    first, second, fourth = block["cells"][0], block["cells"][1], block["cells"][3]
    link_a = _create_cable_link(client, admin_headers, first["id"], second["id"], cable_mark="Ф-QA-A")
    link_b = _create_cable_link(client, admin_headers, second["id"], fourth["id"], cable_mark="Ф-QA-B")

    cable = _create_cable(client, admin_headers, lifecycle_status="reserve")

    # снятие с недопустимым статусом — 422 и состояние не меняется
    bad_return = client.post(
        f"/api/cables/{cable['id']}/return", headers=admin_headers, json={"status": "bogus"}
    )
    body = _problem(bad_return, 422)
    assert body["code"] == "validation.failed", body
    assert "status" in body.get("fields", {}), body
    assert _asset_row(cable["id"])["lifecycle_status"] == "reserve"

    # установка без цели — 422 validation.failed (model_validator схемы)
    no_target = client.post(f"/api/cables/{cable['id']}/install", headers=admin_headers, json={})
    body = _problem(no_target, 422)
    assert body["code"] == "validation.failed", body

    # установка не-кабеля — 422 cable.not_cable
    not_cable = client.post(
        f"/api/cables/{first['id']}/install",
        headers=admin_headers,
        json={"link_id": link_a["id"]},
    )
    body = _problem(not_cable, 422)
    assert body["code"] == "cable.not_cable", body

    # кабель уже установлен на другой связи — 409 cable.already_installed
    assert (
        client.post(
            f"/api/cables/{cable['id']}/install", headers=admin_headers, json={"link_id": link_a["id"]}
        ).status_code
        == 200
    )
    already = client.post(
        f"/api/cables/{cable['id']}/install", headers=admin_headers, json={"link_id": link_b["id"]}
    )
    body = _problem(already, 409)
    assert body["code"] == "cable.already_installed", body
    assert _link_row(link_a["id"])["cable_asset_id"] == cable["id"]
    assert _link_row(link_b["id"])["cable_asset_id"] is None

    # связь занята другим кабелем — 409 cable.link_occupied
    other = _create_cable(client, admin_headers, lifecycle_status="reserve")
    occupied = client.post(
        f"/api/cables/{other['id']}/install",
        headers=admin_headers,
        json={"link_id": link_a["id"]},
    )
    body = _problem(occupied, 409)
    assert body["code"] == "cable.link_occupied", body
    assert _link_row(link_a["id"])["cable_asset_id"] == cable["id"]

    # права на кабельные операции — тоже asset.status.edit
    viewer_headers, viewer_id = _role_headers("viewer")
    try:
        denied = client.post(
            f"/api/cables/{other['id']}/install",
            headers=viewer_headers,
            json={"link_id": link_b["id"]},
        )
        assert _problem(denied, 403)["code"] == "perm.denied"
        denied_return = client.post(
            f"/api/cables/{cable['id']}/return", headers=viewer_headers, json={"status": "reserve"}
        )
        assert _problem(denied_return, 403)["code"] == "perm.denied"
        assert _link_row(link_a["id"])["cable_asset_id"] == cable["id"]
    finally:
        _drop_employee(viewer_id)
