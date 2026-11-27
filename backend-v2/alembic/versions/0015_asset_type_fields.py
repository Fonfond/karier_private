"""Модель оборудования «Карьер», этап 1: поля типа, классы, ячейки, кабель.

Revision ID: 0015_asset_type_fields
Revises: 0014_schema_snapshots
Create Date: 2026-11-26

Что делает миграция (только добавления, ничего не удаляет):

1. ``gis.asset_type_fields`` — поля паспорта типа, из которых фронтенд строит
   динамическую форму реестра (снимает 422 «Проверьте атрибуты объекта»).
   Таблица заполняется из существующих ``asset_types.attr_schema``/
   ``required_attrs``; сами они остаются рабочими (двойная запись).
2. ``gis.asset_types.equipment_class`` + ``group_code`` — класс оборудования и
   вкладка UI. Существующие типы размечены по утверждённой карте (план 31 §2),
   остальные — по названию/старой категории. ``equipment`` = «Прочее»: новые
   типы не должны падать на CHECK, пока админ не выбрал класс.
3. ``gis.assets.cell_kind`` (in/out/sectional), ``cell_no``, ``section_no`` —
   ячейка ПС/БКРУ вместо свободного текста ``schema_role`` и JSONB-полей.
   Значения переносятся из ``schema_role`` и ``attrs`` (cell/section).
4. ``gis.assets.lifecycle_status`` (installed/reserve/repair) — кабельный учёт
   отдельной колонкой, а не CHECK на JSONB ``attrs``: типизировано, проверяется
   БД и не зависит от набора ключей в attrs. Старый ``attrs.reserve`` сохраняется
   и переносится в колонку.
5. Тип ``cable`` («Кабель») создаётся, если его ещё нет, и размечается классом
   ``cable``; поля марки/сечения/длины/состояния попадают в его поля.

Обратная совместимость: ``attr_schema``, ``required_attrs``, ``attrs``,
``schema_role`` и все существующие строки/связи остаются на месте. Откат
(downgrade) убирает только новые колонки и таблицу: производные значения
восстанавливаются из attrs при повторном upgrade, исходные данные не теряются.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

revision: str = "0015_asset_type_fields"
down_revision: str | None = "0014_schema_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- карта классов (эталон: app/services/asset_fields.py) -------------------
# Копия намеренная: data-миграция не должна менять поведение при правках кода.

EXPLICIT_CLASS_BY_CODE: dict[str, str] = {
    # распределительные устройства
    "ps_35": "distribution",
    "ps_35_6_kv": "distribution",
    "ps_35_6_kv_2": "distribution",
    "tps": "distribution",
    "substation": "distribution",
    "bkru": "distribution",
    "bkru_1": "distribution",
    "bkru_2": "distribution",
    "bus_section": "distribution",
    # трансформаторы и сборки
    "ktp": "transformer_assembly",
    "ksr": "transformer_assembly",
    "yaku_1t": "transformer_assembly",
    # коммутационные аппараты
    "yaku": "switching",
    "yakno_vozduh_kabel": "switching",
    "yakno_vozduh_vozduh": "switching",
    "yaku_vozduh_vozduh": "switching",
    # ячейки
    "cell": "cell",
    "tcell": "cell",
    "yacheyka": "cell",
    "yacheyka_2": "cell",
    "yacheyka_3": "cell",
    "yacheyka_5": "cell",
    "yacheyka_7": "cell",
    "yacheyka_16": "cell",
    "yacheyka_21": "cell",
    "yacheyka_bkru_2": "cell",
    "yach_1_f21k": "cell",
    "yach_2_f2_bkru_1": "cell",
    "yach_3_f3_bkru_1": "cell",
    "yach_4_sekcionnaya": "cell",
    "yach_5_f5_bkru_1": "cell",
    "yach_6_f7k": "cell",
    # кабели
    "cable": "cable",
    # мобильное и генерация
    "dmo": "mobile",
    "dmo_dizelnaya_machta_osvescheniya": "mobile",
    "dmp": "mobile",
    "bmp": "mobile",
    "gen_diesel": "mobile",
    "gen_petrol": "mobile",
    "generator_benzinovyy": "mobile",
    "generator_dizelnyy": "mobile",
    "cuckoo": "mobile",
    "mast": "mobile",
    "mo_machta_osvescheniya": "mobile",
    "motopompa_dizelnaya": "mobile",
    "ekg": "mobile",
    "pump": "mobile",
    # опоры и ВЛ
    "op": "line",
    "pole": "line",
    # питающие центры
    "source_35": "source",
}

GROUP_BY_CLASS: dict[str, str] = {
    "distribution": "distribution",
    "transformer_assembly": "transformers",
    "switching": "switching",
    "cell": "cells",
    "cable": "cables",
    "mobile": "mobile",
    "line": "lines",
    "source": "sources",
    "equipment": "other",
}

CLASS_BY_CATEGORY: dict[str, str] = {
    "source": "source",
    "line": "line",
    "pole": "line",
    "mobile": "mobile",
    "lighting": "mobile",
    "aux": "mobile",
    "equipment": "switching",
}

#: Подписи известных полей (копия app.services.asset_fields.FIELD_META).
FIELD_META: dict[str, dict[str, Any]] = {
    "power_kw": {"label": "Мощность", "unit": "кВт", "group": "Мощность", "data_type": "number"},
    "power_kva": {
        "label": "Полная мощность",
        "unit": "кВ·А",
        "group": "Мощность",
        "data_type": "number",
    },
    "voltage_in_kv": {
        "label": "Напряжение на входе",
        "unit": "кВ",
        "group": "Напряжение",
        "data_type": "number",
    },
    "voltage_out_kv": {
        "label": "Напряжение на выходе",
        "unit": "кВ",
        "group": "Напряжение",
        "data_type": "number",
    },
    "voltage_kv": {"label": "Напряжение", "unit": "кВ", "group": "Напряжение", "data_type": "number"},
    "drive_type": {"label": "Тип привода", "group": "Исполнение", "data_type": "text"},
    "fuel_type": {"label": "Тип топлива", "group": "Исполнение", "data_type": "text"},
    "bucket_m3": {"label": "Объём ковша", "unit": "м³", "group": "Основные", "data_type": "number"},
    "section_breaker": {
        "label": "Секционный выключатель",
        "group": "Основные",
        "data_type": "boolean",
    },
    "cable_mark": {"label": "Марка кабеля", "group": "Кабель", "data_type": "text"},
    "section_mm2": {"label": "Сечение", "unit": "мм²", "group": "Кабель", "data_type": "number"},
    "length_m": {"label": "Длина", "unit": "м", "group": "Кабель", "data_type": "number"},
    "lifecycle_status": {
        "label": "Состояние кабеля",
        "group": "Кабель",
        "data_type": "select",
        "options": ["installed", "reserve", "repair"],
    },
    "serial_no": {"label": "Заводской номер", "group": "Паспорт", "data_type": "text"},
    "manufacturer": {"label": "Изготовитель", "group": "Паспорт", "data_type": "text"},
    "model": {"label": "Модель", "group": "Паспорт", "data_type": "text"},
    "commissioned_on": {"label": "Дата ввода", "group": "Паспорт", "data_type": "date"},
}

LEGACY_TO_DATA_TYPE = {
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "date": "date",
    "select": "select",
    "string": "text",
    "text": "text",
}

CABLE_TYPE: dict[str, Any] = {
    "code": "cable",
    "name": "Кабель",
    "category": "line",
    "icon": "🧵",
    "color": "#8B6BFF",
    "sort_order": 120,
    "port_template": {
        "ports": [
            {"code": "IN-1", "name": "Начало", "kind": "in", "voltage_kv": 0.4},
            {"code": "OUT-1", "name": "Конец", "kind": "out", "voltage_kv": 0.4},
        ]
    },
    "attr_schema": {
        "cable_mark": {"type": "string"},
        "section_mm2": {"type": "number", "unit": "мм²", "group_label": "Кабель"},
        "length_m": {"type": "number", "unit": "м", "group_label": "Кабель"},
        "voltage_kv": {"type": "number", "unit": "кВ", "group_label": "Напряжение"},
        "lifecycle_status": {
            "type": "select",
            "options": ["installed", "reserve", "repair"],
            "default": "installed",
        },
    },
    "required_attrs": ["cable_mark", "length_m"],
}

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
    sa.column("sort_order", sa.Integer()),
    sa.column("port_template", postgresql.JSONB()),
    sa.column("attr_schema", postgresql.JSONB()),
    sa.column("required_attrs", postgresql.ARRAY(sa.String())),
    sa.column("is_mobile_default", sa.Boolean()),
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


# --- вспомогательные функции ------------------------------------------------


def _infer_class(code: str | None, name: str | None, category: str | None) -> str:
    code = (code or "").strip().lower()
    name = (name or "").strip().lower()
    if code in EXPLICIT_CLASS_BY_CODE:
        return EXPLICIT_CLASS_BY_CODE[code]
    if code.startswith(("yach_", "yacheyka")) or "ячейк" in name:
        return "cell"
    if code in {"op", "pole"} or "опор" in name:
        return "line"
    if code == "cable" or "кабел" in name:
        return "cable"
    if code.startswith(("ps_", "tps")) or "подстанц" in name or "бкру" in name:
        return "distribution"
    if code in {"ktp", "ksr", "yaku_1t"} or any(
        token in name for token in ("ктп", "кср", "трансформатор")
    ):
        return "transformer_assembly"
    if code.startswith(("yakno", "yaku")) or any(token in name for token in ("якно", "яку")):
        return "switching"
    if any(
        token in name
        for token in ("генератор", "дгу", "дмо", "дмп", "бмп", "мачт", "насос", "экскаватор", "кукушк")
    ):
        return "mobile"
    return CLASS_BY_CATEGORY.get(category or "", "equipment")


def _field_descriptor(
    code: str, rule: dict[str, Any] | None, *, required: bool, sort_order: int
) -> dict[str, Any]:
    rule = rule or {}
    meta = FIELD_META.get(code, {})
    data_type = (
        rule.get("data_type")
        or LEGACY_TO_DATA_TYPE.get(str(rule.get("type") or ""))
        or meta.get("data_type")
        or "text"
    )
    options = rule.get("options") or meta.get("options") or []
    return {
        "code": code,
        "label": rule.get("label") or meta.get("label") or code.replace("_", " ").capitalize(),
        "unit": rule.get("unit") or meta.get("unit"),
        "data_type": data_type,
        "required": bool(required),
        "default_value": rule.get("default", rule.get("default_value")),
        "options": list(options) if isinstance(options, (list, tuple)) else [],
        "min": rule.get("min", rule.get("minimum")),
        "max": rule.get("max", rule.get("maximum")),
        "group_label": rule.get("group_label") or meta.get("group") or "Прочее",
        "sort_order": sort_order,
    }


def _desired_fields(attr_schema: dict[str, Any] | None, required_attrs: list[str] | None) -> list[dict]:
    schema = attr_schema or {}
    required = [str(item) for item in (required_attrs or [])]
    known = list(schema.keys())
    ordered = [code for code in sorted(known) if code in required]
    ordered += [code for code in sorted(known) if code not in required]
    ordered += [code for code in required if code not in schema]
    return [
        _field_descriptor(code, schema.get(code), required=code in required, sort_order=(index + 1) * 10)
        for index, code in enumerate(ordered)
    ]


def _sync_fields(
    bind: sa.Connection,
    asset_type_id: uuid.UUID,
    attr_schema: dict[str, Any] | None,
    required_attrs: list[str] | None,
) -> int:
    """Заполнить/обновить поля типа из attr_schema; лишние строки не трогаем."""
    existing = set(
        bind.execute(
            select(asset_type_fields_tbl.c.code).where(
                asset_type_fields_tbl.c.asset_type_id == asset_type_id
            )
        ).scalars()
    )
    written = 0
    for item in _desired_fields(attr_schema, required_attrs):
        values = {
            "label": item["label"],
            "unit": item["unit"],
            "data_type": item["data_type"],
            "required": item["required"],
            "default_value": item["default_value"],
            "options": item["options"],
            "min": item["min"],
            "max": item["max"],
            "group_label": item["group_label"],
            "sort_order": item["sort_order"],
        }
        if item["code"] in existing:
            bind.execute(
                asset_type_fields_tbl.update()
                .where(
                    asset_type_fields_tbl.c.asset_type_id == asset_type_id,
                    asset_type_fields_tbl.c.code == item["code"],
                )
                .values(**values)
            )
        else:
            bind.execute(
                asset_type_fields_tbl.insert().values(
                    id=uuid.uuid4(), asset_type_id=asset_type_id, code=item["code"], **values
                )
            )
        written += 1
    return written


def _ensure_cable_type(bind: sa.Connection) -> uuid.UUID | None:
    """Создать тип cable (если нет) и вернуть его id; существующий только разметить."""
    existing_id = bind.execute(
        select(asset_types_tbl.c.id).where(asset_types_tbl.c.code == CABLE_TYPE["code"])
    ).scalar_one_or_none()
    if existing_id is not None:
        bind.execute(
            asset_types_tbl.update()
            .where(asset_types_tbl.c.id == existing_id)
            .values(equipment_class="cable", group_code=GROUP_BY_CLASS["cable"])
        )
        return existing_id

    cable_id = uuid.uuid4()
    bind.execute(
        asset_types_tbl.insert().values(
            id=cable_id,
            code=CABLE_TYPE["code"],
            name=CABLE_TYPE["name"],
            category=CABLE_TYPE["category"],
            equipment_class="cable",
            group_code=GROUP_BY_CLASS["cable"],
            icon=CABLE_TYPE["icon"],
            color=CABLE_TYPE["color"],
            port_template=CABLE_TYPE["port_template"],
            attr_schema=CABLE_TYPE["attr_schema"],
            required_attrs=CABLE_TYPE["required_attrs"],
            is_mobile_default=False,
            is_active=True,
            sort_order=CABLE_TYPE["sort_order"],
        )
    )
    return cable_id


def upgrade() -> None:
    # 1. Классы оборудования у типов -----------------------------------------
    op.add_column(
        "asset_types",
        sa.Column("equipment_class", sa.String(length=32), nullable=False, server_default="equipment"),
        schema="gis",
    )
    op.add_column("asset_types", sa.Column("group_code", sa.String(length=32), nullable=True), schema="gis")
    op.create_check_constraint(
        "ck_asset_types_equipment_class",
        "asset_types",
        "equipment_class in ('distribution','transformer_assembly','switching','cell',"
        "'cable','mobile','line','source','equipment')",
        schema="gis",
    )

    # 2. Поля паспорта типа ---------------------------------------------------
    op.create_table(
        "asset_type_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_type_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("data_type", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column("min", sa.Numeric(14, 4), nullable=True),
        sa.Column("max", sa.Numeric(14, 4), nullable=True),
        sa.Column("group_label", sa.String(length=64), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["asset_type_id"], ["gis.asset_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_type_id", "code", name="uq_asset_type_fields_type_code"),
        sa.CheckConstraint(
            "data_type in ('number','integer','text','boolean','date','select')",
            name="ck_asset_type_fields_data_type",
        ),
        schema="gis",
    )
    op.create_index(
        "ix_asset_type_fields_type",
        "asset_type_fields",
        ["asset_type_id", "sort_order"],
        schema="gis",
    )

    # 3. Ячейка и кабельный учёт у объектов ----------------------------------
    op.add_column("assets", sa.Column("cell_kind", sa.String(length=16), nullable=True), schema="gis")
    op.add_column("assets", sa.Column("cell_no", sa.Integer(), nullable=True), schema="gis")
    op.add_column("assets", sa.Column("section_no", sa.Integer(), nullable=True), schema="gis")
    op.add_column(
        "assets", sa.Column("lifecycle_status", sa.String(length=16), nullable=True), schema="gis"
    )
    op.create_check_constraint(
        "ck_assets_cell_kind", "assets", "cell_kind in ('in','out','sectional')", schema="gis"
    )
    op.create_check_constraint(
        "ck_assets_lifecycle_status",
        "assets",
        "lifecycle_status in ('installed','reserve','repair')",
        schema="gis",
    )

    bind = op.get_bind()

    # 4. Разметка классов существующих типов ---------------------------------
    rows = bind.execute(
        select(
            asset_types_tbl.c.id,
            asset_types_tbl.c.code,
            asset_types_tbl.c.name,
            asset_types_tbl.c.category,
        )
    ).all()
    for row in rows:
        equipment_class = _infer_class(row.code, row.name, row.category)
        bind.execute(
            asset_types_tbl.update()
            .where(asset_types_tbl.c.id == row.id)
            .values(equipment_class=equipment_class, group_code=GROUP_BY_CLASS[equipment_class])
        )

    # 5. Кабель как объект реестра ------------------------------------------
    _ensure_cable_type(bind)

    # 6. Поля из attr_schema/required_attrs (включая только что созданный cable)
    rows = bind.execute(
        select(
            asset_types_tbl.c.id,
            asset_types_tbl.c.attr_schema,
            asset_types_tbl.c.required_attrs,
        )
    ).all()
    for row in rows:
        _sync_fields(bind, row.id, row.attr_schema, row.required_attrs)

    # 7. Ячейки: вид/номер/секция из schema_role и attrs ----------------------
    bind.execute(
        sa.text(
            """
            update gis.assets
               set cell_kind = case schema_role
                                 when 'incoming' then 'in'
                                 when 'outgoing' then 'out'
                                 when 'section' then 'sectional'
                               end
             where cell_kind is null
               and schema_role in ('incoming', 'outgoing', 'section')
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update gis.assets
               set cell_no = substring(attrs->>'cell' from '[0-9]+')::int
             where cell_no is null
               and attrs ? 'cell'
               and attrs->>'cell' ~ '[0-9]'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update gis.assets
               set cell_no = (attrs->>'cell_no')::int
             where cell_no is null
               and attrs ? 'cell_no'
               and attrs->>'cell_no' ~ '^[0-9]+$'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update gis.assets
               set section_no = (attrs->>'section_no')::int
             where section_no is null
               and attrs ? 'section_no'
               and attrs->>'section_no' ~ '^[0-9]+$'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update gis.assets
               set section_no = substring(attrs->>'section' from '[0-9]+')::int
             where section_no is null
               and attrs ? 'section'
               and attrs->>'section' ~ '[0-9]'
            """
        )
    )

    # 8. Кабельный статус: старый attrs.reserve и явное значение ---------------
    bind.execute(
        sa.text(
            """
            update gis.assets
               set lifecycle_status = 'reserve'
             where lifecycle_status is null
               and attrs @> '{"reserve": true}'::jsonb
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update gis.assets
               set lifecycle_status = attrs->>'lifecycle_status'
             where lifecycle_status is null
               and attrs->>'lifecycle_status' in ('installed', 'reserve', 'repair')
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update gis.assets a
               set lifecycle_status = 'installed'
              from gis.asset_types t
             where a.asset_type_id = t.id
               and t.equipment_class = 'cable'
               and a.lifecycle_status is null
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Тип cable создан миграцией: убрать, если им ещё не пользуются. Если объекты
    # уже есть — оставляем (данные важнее симметрии отката).
    bind.execute(
        sa.text(
            """
            delete from gis.asset_types t
             where t.code = 'cable'
               and not exists (select 1 from gis.assets a where a.asset_type_id = t.id)
            """
        )
    )

    op.drop_constraint("ck_assets_lifecycle_status", "assets", schema="gis")
    op.drop_constraint("ck_assets_cell_kind", "assets", schema="gis")
    op.drop_column("assets", "lifecycle_status", schema="gis")
    op.drop_column("assets", "section_no", schema="gis")
    op.drop_column("assets", "cell_no", schema="gis")
    op.drop_column("assets", "cell_kind", schema="gis")

    op.drop_index("ix_asset_type_fields_type", table_name="asset_type_fields", schema="gis")
    op.drop_table("asset_type_fields", schema="gis")

    op.drop_constraint("ck_asset_types_equipment_class", "asset_types", schema="gis")
    op.drop_column("asset_types", "group_code", schema="gis")
    op.drop_column("asset_types", "equipment_class", schema="gis")
