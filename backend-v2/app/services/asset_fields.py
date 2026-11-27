"""Поля паспорта типа оборудования: ``gis.asset_type_fields``.

Этап 1 модели «Карьер». Таблица полей — источник правды для динамической формы
реестра и серверной валидации ``POST /api/assets``. Старые
``asset_types.attr_schema``/``required_attrs`` не удаляются: мигратор 0015 и
``sync_from_schema()`` держат их в согласии с таблицей (двойная запись), поэтому
старый клиент и старые вызовы API продолжают работать.

Два направления синхронизации:

* ``sync_from_schema()`` — attr_schema/required_attrs → поля (тип сохранили
  старым API, таблица догоняет);
* ``fields_from_schema()``/``replace_fields()`` — поля → attr_schema/required_attrs
  (админ задал поля конструктором, legacy-схема обновляется).
"""

from __future__ import annotations

import re
import uuid as uuidlib
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AssetType, AssetTypeField
from app.schemas.gis import AssetTypeFieldIn, AssetTypeFieldOut

DATA_TYPES = ("number", "integer", "text", "boolean", "date", "select")

#: Обратная совместимость: старый attr_schema писал type=string/number/…
LEGACY_TO_DATA_TYPE = {
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "date": "date",
    "select": "select",
    "string": "text",
    "text": "text",
}
DATA_TYPE_TO_LEGACY = {
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "date": "date",
    "select": "select",
    "text": "string",
}

#: Класс оборудования → код вкладки UI (``group_code``). Вкладки на этапе 2
#: строятся по group_code, поэтому значения фиксированы и не зависят от вёрстки.
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

#: Разумный класс по старой категории — только для типов, которых нет в карте.
CLASS_BY_CATEGORY: dict[str, str] = {
    "source": "source",
    "line": "line",
    "pole": "line",
    "mobile": "mobile",
    "lighting": "mobile",
    "aux": "mobile",
    "equipment": "switching",
}

#: Словарь подписей известных полей (русский). Эталон для мигратора 0015:
#: там лежит его копия, потому что data-миграции не должны зависеть от кода
#: приложения. На этапе 2 словарь переедет в админ-конструктор полей.
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

EMPTY_VALUES = (None, "")
_NUMBER_TYPES = (int, float, Decimal)


# --- построение описаний полей ---------------------------------------------


def humanize_code(code: str) -> str:
    """Машинный код → подпись, если своего перевода нет: ``power_kw`` → ``Power kw``."""
    words = re.sub(r"[_\-]+", " ", code).strip()
    return words[:1].upper() + words[1:] if words else code


def infer_equipment_class(code: str | None, name: str | None, category: str | None) -> str:
    """Класс оборудования по коду/названию старой категории (карта плана 31)."""
    lowered_code = (code or "").strip().lower()
    lowered_name = (name or "").strip().lower()

    if lowered_code in EXPLICIT_CLASS_BY_CODE:
        return EXPLICIT_CLASS_BY_CODE[lowered_code]
    if lowered_code.startswith(("yach_", "yacheyka")) or "ячейк" in lowered_name:
        return "cell"
    if lowered_code in {"op", "pole"} or "опор" in lowered_name:
        return "line"
    if lowered_code == "cable" or "кабел" in lowered_name:
        return "cable"
    if lowered_code.startswith(("ps_", "tps")) or "подстанц" in lowered_name or "бкру" in lowered_name:
        return "distribution"
    if lowered_code in {"ktp", "ksr", "yaku_1t"} or any(
        token in lowered_name for token in ("ктп", "кср", "трансформатор")
    ):
        return "transformer_assembly"
    if lowered_code.startswith(("yakno", "yaku")) or any(
        token in lowered_name for token in ("якно", "яку")
    ):
        return "switching"
    if any(
        token in lowered_name
        for token in ("генератор", "дгу", "дмо", "дмп", "бмп", "мачт", "насос", "экскаватор", "кукушк")
    ):
        return "mobile"
    return CLASS_BY_CATEGORY.get(category or "", "equipment")


#: Явная карта существующих типов (план 31 §2): код → класс.
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


def group_for_class(equipment_class: str | None) -> str:
    return GROUP_BY_CLASS.get(equipment_class or "equipment", "other")


#: Описание типа «Кабель» — создаётся миграцией 0015 и добивается seed-модулем
#: (``python -m app.seed_equipment_model``) после перезалива демо-данных.
CABLE_TYPE_SPEC: dict[str, Any] = {
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


def effective_class(asset_type: AssetType) -> str:
    """Класс для API: сохранённый в БД, либо выведенный, если стоит «Прочее».

    Нужно после перезалива демо-данных: колонка получила server_default
    ``equipment`` и данные мигратора терялись, пока не выполнен seed-модуль.
    """
    stored = asset_type.equipment_class or "equipment"
    if stored != "equipment":
        return stored
    return infer_equipment_class(asset_type.code, asset_type.name, asset_type.category)


def _rule_min_max(rule: dict[str, Any]) -> tuple[Any, Any]:
    minimum = rule.get("min", rule.get("minimum"))
    maximum = rule.get("max", rule.get("maximum"))
    return minimum, maximum


def field_descriptor(
    code: str,
    rule: dict[str, Any] | None,
    *,
    required: bool,
    sort_order: int,
) -> dict[str, Any]:
    """Описание поля из правила attr_schema + словаря подписей."""
    rule = rule or {}
    meta = FIELD_META.get(code, {})
    data_type = (
        rule.get("data_type")
        or LEGACY_TO_DATA_TYPE.get(str(rule.get("type") or ""))
        or meta.get("data_type")
        or "text"
    )
    if data_type not in DATA_TYPES:
        data_type = "text"
    default_value = rule.get("default", rule.get("default_value"))
    options = rule.get("options") or meta.get("options") or []
    minimum, maximum = _rule_min_max(rule)
    return {
        "code": code,
        "label": rule.get("label") or meta.get("label") or humanize_code(code),
        "unit": rule.get("unit") or meta.get("unit"),
        "data_type": data_type,
        "required": bool(required),
        "default_value": default_value,
        "options": list(options) if isinstance(options, (list, tuple)) else [],
        "min_value": minimum,
        "max_value": maximum,
        "group_label": rule.get("group_label") or meta.get("group") or "Прочее",
        "sort_order": sort_order,
    }


def fields_from_schema(asset_type: AssetType) -> list[dict[str, Any]]:
    """Собрать описания полей из attr_schema/required_attrs типа (мигратор и sync)."""
    schema = asset_type.attr_schema or {}
    required = [str(item) for item in (asset_type.required_attrs or [])]
    known = list(schema.keys())
    ordered = [code for code in sorted(known) if code in required]
    ordered += [code for code in sorted(known) if code not in required]
    ordered += [code for code in required if code not in schema]
    return [
        field_descriptor(code, schema.get(code), required=code in required, sort_order=(index + 1) * 10)
        for index, code in enumerate(ordered)
    ]


def _apply_descriptor(row: AssetTypeField, item: dict[str, Any], *, keep_custom_label: bool) -> None:
    row.data_type = item["data_type"]
    row.required = item["required"]
    row.unit = item["unit"]
    row.default_value = item["default_value"]
    row.options = item["options"]
    row.min_value = item["min_value"]
    row.max_value = item["max_value"]
    row.group_label = item["group_label"]
    row.sort_order = item["sort_order"]
    # Известным полям подпись даёт словарь; для своих кодов (админ задал label)
    # сохраняем прежнюю подпись, чтобы sync не затирал русский текст.
    if not keep_custom_label or item["code"] in FIELD_META:
        row.label = item["label"]


def sync_from_schema(db: Session, asset_type: AssetType) -> None:
    """attr_schema/required_attrs → gis.asset_type_fields (двойная запись).

    Лишние поля не удаляются: таблица — additive-слой, а удаление строки типа
    само каскадно убирает её поля.
    """
    desired = fields_from_schema(asset_type)
    existing = {field.code: field for field in (asset_type.fields or [])}
    for item in desired:
        row = existing.pop(item["code"], None)
        if row is None:
            row = AssetTypeField(id=uuidlib.uuid4(), asset_type_id=asset_type.id, code=item["code"])
            _apply_descriptor(row, item, keep_custom_label=False)
            db.add(row)
        else:
            _apply_descriptor(row, item, keep_custom_label=True)
    db.flush()


def schema_from_fields(items: Sequence[AssetTypeFieldIn] | Sequence[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Поля конструктора → legacy attr_schema/required_attrs (обратная совместимость)."""
    schema: dict[str, Any] = {}
    required: list[str] = []
    for item in items:
        data = item.model_dump() if isinstance(item, AssetTypeFieldIn) else dict(item)
        rule: dict[str, Any] = {"type": DATA_TYPE_TO_LEGACY.get(data.get("data_type", "text"), "string")}
        if data.get("unit"):
            rule["unit"] = data["unit"]
        if data.get("group_label"):
            rule["group_label"] = data["group_label"]
        if data.get("options"):
            rule["options"] = list(data["options"])
        if data.get("default_value") is not None:
            rule["default"] = data["default_value"]
        if data.get("min") is not None:
            rule["min"] = data["min"]
        if data.get("max") is not None:
            rule["max"] = data["max"]
        schema[str(data["code"])] = rule
        if data.get("required"):
            required.append(str(data["code"]))
    return schema, required


def replace_fields(
    db: Session, asset_type: AssetType, items: Sequence[AssetTypeFieldIn]
) -> tuple[dict[str, Any], list[str]]:
    """Полностью заменить поля типа (админ-конструктор) и обновить legacy-схему."""
    for row in list(asset_type.fields or []):
        db.delete(row)
    db.flush()
    schema, required = schema_from_fields(items)
    for index, item in enumerate(items):
        sort_order = item.sort_order or (index + 1) * 10
        row = AssetTypeField(
            id=uuidlib.uuid4(),
            asset_type_id=asset_type.id,
            code=item.code,
            label=item.label,
            unit=item.unit,
            data_type=item.data_type,
            required=item.required,
            default_value=item.default_value,
            options=list(item.options or []),
            min_value=item.min,
            max_value=item.max,
            group_label=item.group_label,
            sort_order=sort_order,
        )
        db.add(row)
    asset_type.attr_schema = schema
    asset_type.required_attrs = required
    db.flush()
    return schema, required


# --- публичное представление ------------------------------------------------


def field_out(field: AssetTypeField) -> AssetTypeFieldOut:
    return AssetTypeFieldOut(
        id=field.id,
        code=field.code,
        label=field.label,
        unit=field.unit,
        data_type=field.data_type,
        required=bool(field.required),
        default_value=field.default_value,
        options=list(field.options or []),
        min=float(field.min_value) if field.min_value is not None else None,
        max=float(field.max_value) if field.max_value is not None else None,
        group_label=field.group_label,
        sort_order=field.sort_order or 0,
    )


def public_fields(asset_type: AssetType) -> list[AssetTypeFieldOut]:
    rows = sorted(asset_type.fields or [], key=lambda row: (row.sort_order or 0, row.code))
    if rows:
        return [field_out(row) for row in rows]
    # Таблица полей ещё не заполнена (перезалив демо-данных в обход мигратора):
    # отдаём поля, выведенные из attr_schema, чтобы форма не осталась пустой.
    return [
        AssetTypeFieldOut(
            id=uuidlib.uuid5(asset_type.id, item["code"]),
            code=item["code"],
            label=item["label"],
            unit=item["unit"],
            data_type=item["data_type"],
            required=item["required"],
            default_value=item["default_value"],
            options=item["options"],
            min=float(item["min_value"]) if item["min_value"] is not None else None,
            max=float(item["max_value"]) if item["max_value"] is not None else None,
            group_label=item["group_label"],
            sort_order=item["sort_order"],
        )
        for item in fields_from_schema(asset_type)
    ]


# --- идемпотентное наполнение (после загрузки демо-данных) -------------------


def ensure_cable_type(db: Session) -> AssetType:
    """Создать тип «Кабель», если его нет; существующий только разметить."""
    asset_type = db.scalar(select(AssetType).where(AssetType.code == CABLE_TYPE_SPEC["code"]))
    if asset_type is None:
        asset_type = AssetType(
            id=uuidlib.uuid4(),
            code=CABLE_TYPE_SPEC["code"],
            name=CABLE_TYPE_SPEC["name"],
            category=CABLE_TYPE_SPEC["category"],
            equipment_class="cable",
            group_code=GROUP_BY_CLASS["cable"],
            icon=CABLE_TYPE_SPEC["icon"],
            color=CABLE_TYPE_SPEC["color"],
            port_template=CABLE_TYPE_SPEC["port_template"],
            attr_schema=CABLE_TYPE_SPEC["attr_schema"],
            required_attrs=CABLE_TYPE_SPEC["required_attrs"],
            is_mobile_default=False,
            is_active=True,
            sort_order=CABLE_TYPE_SPEC["sort_order"],
        )
        db.add(asset_type)
        db.flush()
        sync_from_schema(db, asset_type)
        return asset_type
    if asset_type.equipment_class != "cable":
        asset_type.equipment_class = "cable"
    if not asset_type.group_code:
        asset_type.group_code = GROUP_BY_CLASS["cable"]
    db.flush()
    return asset_type


def backfill_cell_columns(db: Session) -> dict[str, int]:
    """Перенести ячейки/кабель из schema_role и attrs в типизированные колонки.

    Идемпотентно: трогает только строки, где колонка ещё NULL.
    """
    statements = {
        "cell_kind": """
            update gis.assets
               set cell_kind = case schema_role
                                 when 'incoming' then 'in'
                                 when 'outgoing' then 'out'
                                 when 'section' then 'sectional'
                               end
             where cell_kind is null
               and schema_role in ('incoming', 'outgoing', 'section')
        """,
        "cell_no": """
            update gis.assets
               set cell_no = substring(attrs->>'cell' from '[0-9]+')::int
             where cell_no is null
               and attrs ? 'cell'
               and attrs->>'cell' ~ '[0-9]'
        """,
        "cell_no_attr": """
            update gis.assets
               set cell_no = (attrs->>'cell_no')::int
             where cell_no is null
               and attrs ? 'cell_no'
               and attrs->>'cell_no' ~ '^[0-9]+$'
        """,
        "section_no_attr": """
            update gis.assets
               set section_no = (attrs->>'section_no')::int
             where section_no is null
               and attrs ? 'section_no'
               and attrs->>'section_no' ~ '^[0-9]+$'
        """,
        "section_no": """
            update gis.assets
               set section_no = substring(attrs->>'section' from '[0-9]+')::int
             where section_no is null
               and attrs ? 'section'
               and attrs->>'section' ~ '[0-9]'
        """,
        "cable_reserve": """
            update gis.assets
               set lifecycle_status = 'reserve'
             where lifecycle_status is null
               and attrs @> '{"reserve": true}'::jsonb
        """,
        "cable_status_attr": """
            update gis.assets
               set lifecycle_status = attrs->>'lifecycle_status'
             where lifecycle_status is null
               and attrs->>'lifecycle_status' in ('installed', 'reserve', 'repair')
        """,
        "cable_default": """
            update gis.assets a
               set lifecycle_status = 'installed'
              from gis.asset_types t
             where a.asset_type_id = t.id
               and t.equipment_class = 'cable'
               and a.lifecycle_status is null
        """,
    }
    counts: dict[str, int] = {}
    for name, sql in statements.items():
        result = db.execute(text(sql))
        counts[name] = result.rowcount or 0
    return counts


def backfill_equipment_model(db: Session) -> dict[str, int]:
    """Идемпотентно добрать классы, поля типа и колонки ячеек/кабеля.

    Миграция 0015 делает это для данных, существующих на момент upgrade. Если
    данные залиты позже (демо-дамп поверх схемы), вызывается этот метод:
    ``python -m app.seed_equipment_model``. Повторный вызов ничего не ломает.
    """
    counts = {"classes": 0, "group_codes": 0, "type_fields": 0}
    for asset_type in db.scalars(select(AssetType)).all():
        inferred = infer_equipment_class(asset_type.code, asset_type.name, asset_type.category)
        if (asset_type.equipment_class or "equipment") == "equipment" and inferred != "equipment":
            asset_type.equipment_class = inferred
            counts["classes"] += 1
        if not asset_type.group_code:
            asset_type.group_code = group_for_class(asset_type.equipment_class)
            counts["group_codes"] += 1
        if not asset_type.fields and asset_type.attr_schema:
            desired = fields_from_schema(asset_type)
            sync_from_schema(db, asset_type)
            counts["type_fields"] += len(desired)
    ensure_cable_type(db)
    db.flush()
    counts.update({f"assets_{key}": value for key, value in backfill_cell_columns(db).items()})
    # Новые поля добавлены через db.add: уже загруженная коллекция их не видит.
    db.expire_all()
    return counts


# --- валидация паспорта -----------------------------------------------------


def _validation_descriptors(asset_type: AssetType) -> list[dict[str, Any]]:
    """Поля типа; если таблица ещё пуста — синтез из legacy attr_schema."""
    rows = sorted(asset_type.fields or [], key=lambda row: (row.sort_order or 0, row.code))
    if rows:
        return [
            {
                "code": row.code,
                "label": row.label,
                "data_type": row.data_type,
                "required": bool(row.required),
                "options": list(row.options or []),
                "min_value": row.min_value,
                "max_value": row.max_value,
            }
            for row in rows
        ]
    # Тип, созданный в обход мигратора/конструктора: старое поведение сохраняем.
    schema = asset_type.attr_schema or {}
    required = {str(item) for item in (asset_type.required_attrs or [])}
    descriptors = []
    for code in list(schema.keys()) + [code for code in required if code not in schema]:
        item = field_descriptor(code, schema.get(code), required=code in required, sort_order=0)
        descriptors.append(
            {
                "code": item["code"],
                "label": item["label"],
                "data_type": item["data_type"],
                "required": item["required"],
                "options": item["options"],
                "min_value": item["min_value"],
                "max_value": item["max_value"],
            }
        )
    return descriptors


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return not value
    return False


def _check_value(descriptor: dict[str, Any], value: Any) -> str | None:
    """Проверить одно значение; вернуть русское сообщение об ошибке или None."""
    data_type = descriptor.get("data_type") or "text"
    if data_type == "number":
        if isinstance(value, bool) or not isinstance(value, _NUMBER_TYPES):
            return "Ожидается число"
    elif data_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return "Ожидается целое число"
    elif data_type == "boolean":
        if not isinstance(value, bool):
            return "Ожидается да/нет"
    elif data_type == "date":
        if isinstance(value, (date, datetime)):
            return None
        if not isinstance(value, str):
            return "Ожидается дата в формате ГГГГ-ММ-ДД"
        try:
            datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except ValueError:
            return "Ожидается дата в формате ГГГГ-ММ-ДД"
        return None
    elif data_type == "select":
        options = descriptor.get("options") or []
        if options and value not in options and str(value) not in {str(item) for item in options}:
            allowed = ", ".join(str(item) for item in options)
            return f"Недопустимое значение (допустимо: {allowed})"
        return None
    else:  # text
        if isinstance(value, (dict, list)):
            return "Ожидается текст"

    minimum = descriptor.get("min_value")
    maximum = descriptor.get("max_value")
    if isinstance(value, _NUMBER_TYPES) and not isinstance(value, bool):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "Ожидается число"
        if minimum is not None and number < float(minimum):
            return f"Значение меньше минимального ({minimum:g})"
        if maximum is not None and number > float(maximum):
            return f"Значение больше максимального ({maximum:g})"
    return None


def validate_asset_fields(
    asset_type: AssetType, attrs: dict[str, Any], *, check_required: bool = True
) -> tuple[dict[str, str], dict[str, str]]:
    """Проверить attrs по полям типа. Возвращает ``(errors, field_labels)``.

    ``check_required=False`` — для ячеек/элементов блока: паспорт заполняется
    позже в карточке, схема не должна блокировать правку.
    """
    errors: dict[str, str] = {}
    labels: dict[str, str] = {}
    attrs = attrs or {}

    for descriptor in _validation_descriptors(asset_type):
        code = descriptor["code"]
        label = descriptor.get("label") or humanize_code(code)
        value = attrs.get(code)
        if _is_empty(value):
            if descriptor.get("required") and check_required:
                errors[code] = "Обязательное поле"
                labels[code] = label
            continue
        message = _check_value(descriptor, value)
        if message:
            errors[code] = message
            labels[code] = label
    return errors, labels


def validation_detail(labels: dict[str, str], errors: dict[str, str]) -> str:
    """Читаемый русский текст ошибки: «Проверьте поля объекта: Мощность, …»."""
    names = [labels.get(code) or humanize_code(code) for code in errors]
    if not names:
        return "Проверьте поля объекта"
    if len(names) > 4:
        head = ", ".join(names[:4])
        return f"Проверьте поля объекта: {head} и ещё {len(names) - 4}"
    return "Проверьте поля объекта: " + ", ".join(names)
