"""Модель оборудования «Карьер», этап 2: кабельный FK и шаблоны БКРУ/ПС/КТП.

Revision ID: 0016_stage2_equipment
Revises: 0015_asset_type_fields
Create Date: 2026-11-26

Миграция только добавляет (ни одна таблица/колонка/строка не удаляется):

1. ``gis.links.cable_asset_id`` — кабель-объект реестра, установленный на участок
   связи. ``FK gis.assets(id) ON DELETE SET NULL`` (удалили кабель — связь жива,
   просто без кабеля), nullable + индекс ``ix_links_cable_asset``.
   Старые денормализованные поля ``cable_mark``/``cable_no``/``length_m``/
   ``cross_section_mm2`` остаются: отчёты и старый клиент работают как раньше.
2. ``asset_types.composite_template`` v2 для БКРУ, ПС 35/6 и КТП + ``is_composite``.
   Формат v2 — список (совместим со старым админ-клиентом, который делает
   ``composite_template.map``): элемент-метаданные ``{"version": 2, ...}`` и далее
   по элементу на секцию с упорядоченным списком ``cells``
   (``cell_kind``: in/out/sectional). v1-шаблоны Спринта 21 не перезаписываются,
   если тип не попал в профили БКРУ/ПС/КТП.
3. Тип ``razedinitel`` («Разъединитель», класс ``switching``) — вводной
   разъединитель КТП. Создаётся, только если его ещё нет; поля паспорта
   добавляются в ``gis.asset_type_fields`` (этап 1). Существующий тип только
   размечается.

Обратная совместимость: ``composite_template`` v1, порты, поля и объекты не
меняются; новые ключи JSONB читает только код этапа 2 (и старый клиент — как
массив, не падая). Откат удаляет FK/индекс и возвращает шаблоны к ``[]`` только
там, где они всё ещё совпадают с сидовыми: изменения админа не теряются.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

revision: str = "0016_stage2_equipment"
down_revision: str | None = "0015_asset_type_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATE_VERSION = 2

CELL_KIND_TITLES = {"in": "Вводная", "out": "Отходящая", "sectional": "Секционная"}

# --- Копия канонических шаблонов (эталон: app/services/equipment_templates.py) --
# Копия намеренная: data-миграция не должна менять поведение при правках кода.

BKRU_SECTIONS = (
    (1, "Секция 1", 6.0, (("in", 1), ("out", 2), ("sectional", 1))),
    (2, "Секция 2", 6.0, (("out", 1), ("in", 1))),
)
PS_SECTIONS = ((1, "Секция 1 (35 кВ)", 35.0), (2, "Секция 2 (6 кВ)", 6.0))
PS_DEFAULT_CELLS = 17
KTP_DISCONNECTOR = {
    "cell_kind": "in",
    "type_code": "razedinitel",
    "label": "Вводной разъединитель",
    "voltage_kv": 6.0,
}

BKRU_CODES = {"bkru", "bkru_1", "bkru_2", "bkru_bkru", "bkru_standard"}
KTP_CODES = {"ktp", "ktp_1", "ktp_2"}
PS_CODES = {"ps_35", "ps_35_6_kv", "ps_35_6_kv_2", "ps_35_6", "substation", "tps"}

DISCONNECTOR_TYPE = {
    "code": "razedinitel",
    "name": "Разъединитель",
    "category": "equipment",
    "equipment_class": "switching",
    "group_code": "switching",
    "icon": "⏻",
    "color": "#F59E0B",
    "schema_symbol": "disconnector",
    "sort_order": 190,
    "port_template": {
        "ports": [
            {"code": "IN-1", "name": "Ввод", "kind": "in", "voltage_kv": 6.0},
            {"code": "OUT-1", "name": "Выход", "kind": "out", "voltage_kv": 6.0},
        ]
    },
    "attr_schema": {
        "voltage_kv": {"type": "number", "unit": "кВ", "group_label": "Напряжение"},
        "drive_type": {"type": "string", "group_label": "Исполнение"},
    },
    "required_attrs": [],
}

DISCONNECTOR_FIELDS = (
    {
        "code": "voltage_kv",
        "label": "Напряжение",
        "unit": "кВ",
        "data_type": "number",
        "required": False,
        "group_label": "Напряжение",
        "sort_order": 10,
    },
    {
        "code": "drive_type",
        "label": "Тип привода",
        "unit": None,
        "data_type": "text",
        "required": False,
        "group_label": "Исполнение",
        "sort_order": 20,
    },
)

asset_types_tbl = sa.table(
    "asset_types",
    sa.column("id", sa.Uuid()),
    sa.column("code", sa.String()),
    sa.column("name", sa.String()),
    sa.column("category", sa.String()),
    sa.column("equipment_class", sa.String()),
    sa.column("group_code", sa.String()),
    sa.column("icon", sa.String()),
    sa.column("color", sa.String()),
    sa.column("schema_symbol", sa.String()),
    sa.column("sort_order", sa.Integer()),
    sa.column("port_template", postgresql.JSONB()),
    sa.column("attr_schema", postgresql.JSONB()),
    sa.column("required_attrs", postgresql.ARRAY(sa.String())),
    sa.column("is_mobile_default", sa.Boolean()),
    sa.column("is_composite", sa.Boolean()),
    sa.column("composite_template", postgresql.JSONB()),
    sa.column("is_active", sa.Boolean()),
    schema="gis",
)

asset_type_fields_tbl = sa.table(
    "asset_type_fields",
    sa.column("id", sa.Uuid()),
    sa.column("asset_type_id", sa.Uuid()),
    sa.column("code", sa.String()),
    sa.column("label", sa.String()),
    sa.column("unit", sa.String()),
    sa.column("data_type", sa.String()),
    sa.column("required", sa.Boolean()),
    sa.column("default_value", postgresql.JSONB()),
    sa.column("options", postgresql.JSONB()),
    sa.column("min", sa.Numeric(14, 4)),
    sa.column("max", sa.Numeric(14, 4)),
    sa.column("group_label", sa.String()),
    sa.column("sort_order", sa.Integer()),
    schema="gis",
)


# --- шаблоны (копия логики app/services/equipment_templates.py) --------------


def _cell_entry(cell_kind: str, count: int = 1, label: str | None = None, *, voltage_kv=None) -> dict:
    cell_kind = str(cell_kind or "out").strip().lower()
    if cell_kind not in CELL_KIND_TITLES:
        cell_kind = "out"
    entry: dict[str, Any] = {
        "cell_kind": cell_kind,
        "count": max(1, int(count or 1)),
        "label": label or CELL_KIND_TITLES[cell_kind],
    }
    if voltage_kv is not None:
        entry["voltage_kv"] = voltage_kv
    return entry


def _ps_section_cells(cells_per_section: int) -> list[tuple[str, int]]:
    if cells_per_section <= 1:
        return [("in", 1)]
    return [("in", 1), ("out", cells_per_section - 2), ("sectional", 1)]


def builtin_template(profile: str) -> list[dict[str, Any]]:
    if profile == "bkru":
        template: list[dict[str, Any]] = [
            {
                "version": TEMPLATE_VERSION,
                "profile": "bkru",
                "title": "БКРУ (6 ячеек)",
                "configurable": False,
                "cells": 6,
            }
        ]
        for section_no, label, voltage, cells in BKRU_SECTIONS:
            template.append(
                {
                    "version": TEMPLATE_VERSION,
                    "section_no": section_no,
                    "label": label,
                    "voltage_kv": voltage,
                    "cells": [
                        _cell_entry(kind, count, voltage_kv=voltage) for kind, count in cells
                    ],
                }
            )
        return template
    if profile == "ps_35_6":
        template = [
            {
                "version": TEMPLATE_VERSION,
                "profile": "ps_35_6",
                "title": "ПС 35/6 кВ (17 ячеек на секцию)",
                "configurable": True,
                "cells_per_section": PS_DEFAULT_CELLS,
                "section_count": len(PS_SECTIONS),
            }
        ]
        for section_no, label, voltage in PS_SECTIONS:
            template.append(
                {
                    "version": TEMPLATE_VERSION,
                    "section_no": section_no,
                    "label": label,
                    "voltage_kv": voltage,
                    "cells": [
                        _cell_entry(kind, count, voltage_kv=voltage)
                        for kind, count in _ps_section_cells(PS_DEFAULT_CELLS)
                    ],
                }
            )
        return template
    if profile == "ktp":
        return [
            {
                "version": TEMPLATE_VERSION,
                "profile": "ktp",
                "title": "КТП (без ячеек, вводной разъединитель)",
                "configurable": False,
                "cells": 0,
                "disconnector": dict(KTP_DISCONNECTOR),
            }
        ]
    return []


def profile_for_type(code: str | None, name: str | None) -> str | None:
    code_norm = (code or "").strip().lower()
    name_norm = (name or "").strip().lower()
    if code_norm in BKRU_CODES or "бкру" in name_norm:
        return "bkru"
    if code_norm in KTP_CODES or "ктп" in name_norm:
        return "ktp"
    if code_norm in PS_CODES or "пс-" in name_norm or "пс " in name_norm or "подстанц" in name_norm:
        return "ps_35_6"
    return None


# --- вспомогательные функции ------------------------------------------------


def _ensure_disconnector_type(bind: sa.Connection) -> uuid.UUID:
    existing = bind.execute(
        select(asset_types_tbl.c.id).where(asset_types_tbl.c.code == DISCONNECTOR_TYPE["code"])
    ).scalar_one_or_none()
    if existing is not None:
        bind.execute(
            asset_types_tbl.update()
            .where(asset_types_tbl.c.id == existing)
            .values(is_active=True)
        )
        return existing

    type_id = uuid.uuid4()
    bind.execute(
        asset_types_tbl.insert().values(
            id=type_id,
            code=DISCONNECTOR_TYPE["code"],
            name=DISCONNECTOR_TYPE["name"],
            category=DISCONNECTOR_TYPE["category"],
            equipment_class=DISCONNECTOR_TYPE["equipment_class"],
            group_code=DISCONNECTOR_TYPE["group_code"],
            icon=DISCONNECTOR_TYPE["icon"],
            color=DISCONNECTOR_TYPE["color"],
            schema_symbol=DISCONNECTOR_TYPE["schema_symbol"],
            sort_order=DISCONNECTOR_TYPE["sort_order"],
            port_template=DISCONNECTOR_TYPE["port_template"],
            attr_schema=DISCONNECTOR_TYPE["attr_schema"],
            required_attrs=list(DISCONNECTOR_TYPE["required_attrs"]),
            is_mobile_default=False,
            is_composite=False,
            composite_template=[],
            is_active=True,
        )
    )
    for field in DISCONNECTOR_FIELDS:
        bind.execute(
            asset_type_fields_tbl.insert().values(
                id=uuid.uuid4(),
                asset_type_id=type_id,
                code=field["code"],
                label=field["label"],
                unit=field["unit"],
                data_type=field["data_type"],
                required=field["required"],
                default_value=None,
                options=[],
                min=None,
                max=None,
                group_label=field["group_label"],
                sort_order=field["sort_order"],
            )
        )
    return type_id


def upgrade() -> None:
    # 1. Кабельный учёт: связь ссылается на кабель-объект --------------------
    op.add_column(
        "links", sa.Column("cable_asset_id", sa.Uuid(), nullable=True), schema="gis"
    )
    op.create_foreign_key(
        "fk_links_cable_asset_assets",
        "links",
        "assets",
        ["cable_asset_id"],
        ["id"],
        source_schema="gis",
        referent_schema="gis",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_links_cable_asset", "links", ["cable_asset_id"], schema="gis"
    )

    bind = op.get_bind()

    # 2. Вводной разъединитель КТП: тип класса switching ----------------------
    _ensure_disconnector_type(bind)

    # 3. Шаблоны v2 БКРУ / ПС 35/6 / КТП -------------------------------------
    rows = bind.execute(
        select(asset_types_tbl.c.id, asset_types_tbl.c.code, asset_types_tbl.c.name)
    ).all()
    for row in rows:
        profile = profile_for_type(row.code, row.name)
        if profile is None:
            continue
        bind.execute(
            asset_types_tbl.update()
            .where(asset_types_tbl.c.id == row.id)
            .values(is_composite=True, composite_template=builtin_template(profile))
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Шаблоны, которые всё ещё совпадают с сидовыми, возвращаем к пустому
    # v1-шаблону. Если админ отредактировал состав — оставляем как есть.
    rows = bind.execute(
        select(
            asset_types_tbl.c.id,
            asset_types_tbl.c.code,
            asset_types_tbl.c.name,
            asset_types_tbl.c.composite_template,
        )
    ).all()
    for row in rows:
        profile = profile_for_type(row.code, row.name)
        if profile is None:
            continue
        if row.composite_template == builtin_template(profile):
            bind.execute(
                asset_types_tbl.update()
                .where(asset_types_tbl.c.id == row.id)
                .values(is_composite=False, composite_template=[])
            )

    # Тип «Разъединитель» создан миграцией: убираем, только если им не пользуются.
    bind.execute(
        sa.text(
            """
            delete from gis.asset_types t
             where t.code = 'razedinitel'
               and not exists (select 1 from gis.assets a where a.asset_type_id = t.id)
            """
        )
    )

    op.drop_index("ix_links_cable_asset", table_name="links", schema="gis")
    op.drop_constraint("fk_links_cable_asset_assets", "links", schema="gis")
    op.drop_column("links", "cable_asset_id", schema="gis")
