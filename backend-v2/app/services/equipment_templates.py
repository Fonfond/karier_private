"""Шаблоны составных устройств «Карьер» этапа 2: БКРУ, ПС 35/6, КТП.

Модель ``asset_types.composite_template`` v2 — это **список** (не словарь!), чтобы
не ломать старый админ-клиент, который делает ``(type.composite_template ?? []).map``:

1. первый элемент — метаданные шаблона (``{"version": 2, "profile": ..., ...}``);
2. дальше по элементу на секцию: ``section_no``, ``label``, ``voltage_kv`` и
   упорядоченный список ``cells`` вида
   ``{"cell_kind": "in|out|sectional", "count": 1, "label": "Вводная"}``.

Порядок ячеек внутри шаблона = порядок создания и порядок на схеме. Для БКРУ он
задан явно (секция 1: вводная, отходящая ×2, секционная; секция 2: отходящая,
вводная) — ровно 6 ячеек. Для ПС 35/6 состав секции вычисляется из параметра
``cells_per_section`` (по умолчанию 17: вводная + 15 отходящих + секционная).

Старый формат v1 (``[{"type_code": "cell", "count": 6, "label": "Яч."}]`` из
Спринта 21) продолжает читаться: он превращается в одну секцию с отходящими
ячейками. Обратная совместимость нужна, потому что типы, созданные до этапа 2,
могут иметь именно такой шаблон.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import AssetType

#: Версия формата шаблона (этап 2).
TEMPLATE_VERSION = 2

#: Допустимые виды ячеек (совпадают с CHECK ``gis.assets.cell_kind``).
CELL_KINDS = ("in", "out", "sectional")

CELL_KIND_TITLES: dict[str, str] = {
    "in": "Вводная",
    "out": "Отходящая",
    "sectional": "Секционная",
}

#: Старая роль элемента схемы (``schema_role``) — пишется рядом с ``cell_kind``,
#: чтобы отчёты/схема Спринта 21 видели привычные значения.
SCHEMA_ROLE_BY_CELL_KIND: dict[str, str] = {
    "in": "incoming",
    "out": "outgoing",
    "sectional": "section",
}

CELL_KIND_BY_SCHEMA_ROLE: dict[str, str] = {
    "incoming": "in",
    "outgoing": "out",
    "section": "sectional",
}

PROFILE_BKRU = "bkru"
PROFILE_PS = "ps_35_6"
PROFILE_KTP = "ktp"

PROFILE_TITLES: dict[str, str] = {
    PROFILE_BKRU: "БКРУ (6 ячеек)",
    PROFILE_PS: "ПС 35/6 кВ (17 ячеек на секцию)",
    PROFILE_KTP: "КТП (без ячеек, вводной разъединитель)",
}

#: ПС 35/6: сколько секций создаёт шаблон и какое напряжение у секции.
PS_SECTIONS: tuple[tuple[int, str, float], ...] = (
    (1, "Секция 1 (35 кВ)", 35.0),
    (2, "Секция 2 (6 кВ)", 6.0),
)

#: Шаблон БКРУ: ровно 6 ячеек, порядок зафиксирован заданием этапа 2.
BKRU_SECTIONS: tuple[tuple[int, str, float, tuple[tuple[str, int], ...]], ...] = (
    (1, "Секция 1", 6.0, (("in", 1), ("out", 2), ("sectional", 1))),
    (2, "Секция 2", 6.0, (("out", 1), ("in", 1))),
)

#: КТП: ячеек нет, есть только вводной разъединитель (объект класса switching).
KTP_DISCONNECTOR: dict[str, Any] = {
    "cell_kind": "in",
    "type_code": "razedinitel",
    "label": "Вводной разъединитель",
    "voltage_kv": 6.0,
}

#: Тип «Разъединитель»: создаётся миграцией/сидом, если в справочнике нет
#: подходящего коммутационного аппарата. Нужен КТП для вводного разъединителя.
DISCONNECTOR_TYPE_SPEC: dict[str, Any] = {
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

#: Какие коды/названия типов получают готовый шаблон этапа 2.
BKRU_CODES = {"bkru", "bkru_1", "bkru_2", "bkru_bkru", "bkru_standard"}
KTP_CODES = {"ktp", "ktp_1", "ktp_2"}
PS_CODES = {"ps_35", "ps_35_6_kv", "ps_35_6_kv_2", "ps_35_6", "substation", "tps"}


# --- разбор и сборка шаблона ------------------------------------------------


@dataclass
class CellBlueprint:
    """Ячейка, которую нужно создать: вид, секция и подпись."""

    cell_kind: str
    section_no: int
    label: str
    voltage_kv: float | None = None
    type_code: str | None = None


@dataclass
class SectionSpec:
    section_no: int
    label: str
    voltage_kv: float | None = None
    cells: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParsedTemplate:
    """Разобранный шаблон любого формата (v2, v1, dict из плана 31)."""

    version: int = 0
    profile: str | None = None
    configurable: bool = False
    cells_per_section: int | None = None
    sections: list[SectionSpec] = field(default_factory=list)
    disconnector: dict[str, Any] | None = None

    @property
    def is_v2(self) -> bool:
        return self.version >= TEMPLATE_VERSION

    @property
    def empty(self) -> bool:
        return not self.sections and self.disconnector is None


def _cell_entry(
    cell_kind: str, count: int = 1, label: str | None = None, *, voltage_kv: float | None = None
) -> dict[str, Any]:
    cell_kind = str(cell_kind or "out").strip().lower()
    if cell_kind not in CELL_KINDS:
        cell_kind = "out"
    return {
        "cell_kind": cell_kind,
        "count": max(1, int(count or 1)),
        "label": label or CELL_KIND_TITLES[cell_kind],
        **({"voltage_kv": voltage_kv} if voltage_kv is not None else {}),
    }


def builtin_template(profile: str, *, cells_per_section: int | None = None) -> list[dict[str, Any]]:
    """Канонический v2-шаблон профиля (список: мета + секции)."""
    if profile == PROFILE_BKRU:
        meta = {
            "version": TEMPLATE_VERSION,
            "profile": PROFILE_BKRU,
            "title": PROFILE_TITLES[PROFILE_BKRU],
            "configurable": False,
            "cells": 6,
        }
        template: list[dict[str, Any]] = [meta]
        for section_no, label, voltage, cells in BKRU_SECTIONS:
            template.append(
                {
                    "version": TEMPLATE_VERSION,
                    "section_no": section_no,
                    "label": label,
                    "voltage_kv": voltage,
                    "cells": [
                        _cell_entry(kind, count, voltage_kv=voltage)
                        for kind, count in cells
                    ],
                }
            )
        return template

    if profile == PROFILE_PS:
        per_section = _normalize_cells_per_section(cells_per_section) or 17
        meta = {
            "version": TEMPLATE_VERSION,
            "profile": PROFILE_PS,
            "title": PROFILE_TITLES[PROFILE_PS],
            "configurable": True,
            "cells_per_section": per_section,
            "section_count": len(PS_SECTIONS),
        }
        template = [meta]
        for section_no, label, voltage in PS_SECTIONS:
            template.append(
                {
                    "version": TEMPLATE_VERSION,
                    "section_no": section_no,
                    "label": label,
                    "voltage_kv": voltage,
                    "cells": [
                        _cell_entry(kind, count, voltage_kv=voltage)
                        for kind, count in _ps_section_cells(per_section)
                    ],
                }
            )
        return template

    if profile == PROFILE_KTP:
        return [
            {
                "version": TEMPLATE_VERSION,
                "profile": PROFILE_KTP,
                "title": PROFILE_TITLES[PROFILE_KTP],
                "configurable": False,
                "cells": 0,
                "disconnector": dict(KTP_DISCONNECTOR),
            }
        ]

    raise ApiError(400, "composite.unknown_profile", f"Неизвестный шаблон состава: {profile}")


def _normalize_cells_per_section(value: int | None) -> int | None:
    """Разрешённый диапазон параметра ПС: 1…50 (None — взять из шаблона)."""
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - защита от прямых вызовов
        raise ApiError(422, "validation.failed", "cells_per_section должен быть целым числом") from exc
    if not 1 <= number <= 50:
        raise ApiError(
            422,
            "validation.failed",
            "cells_per_section должен быть в диапазоне 1…50",
            fields={"cells_per_section": "Допустимо от 1 до 50"},
        )
    return number


def _ps_section_cells(cells_per_section: int) -> list[tuple[str, int]]:
    """Состав секции ПС: 1 вводная + (n-2) отходящих + 1 секционная.

    Для n=1 остаётся только вводная (иначе отходящих было бы отрицательное
    число); для n=2 — вводная и секционная. Итого ровно ``n`` ячеек при n ≥ 2.
    """
    if cells_per_section <= 1:
        return [("in", 1)]
    return [("in", 1), ("out", cells_per_section - 2), ("sectional", 1)]


def _is_meta(entry: dict[str, Any]) -> bool:
    """Элемент-метаданные шаблона: ``{"version": 2, "profile": …, "cells": 6}``.

    У секции ``cells`` — список ячеек; у меты — число (сколько всего ячеек) или
    ключа нет вовсе. Различаем по типу значения, а не по наличию ключа.
    """
    if "section_no" in entry or "type_code" in entry:
        return False
    return not isinstance(entry.get("cells"), list)


def _parse_v2_list(raw: list[Any]) -> ParsedTemplate | None:
    entries = [entry for entry in raw if isinstance(entry, dict)]
    if not entries:
        return None
    meta = entries[0] if _is_meta(entries[0]) else {}
    if not meta and not any("cells" in entry for entry in entries):
        return None

    parsed = ParsedTemplate(
        version=int(meta.get("version") or TEMPLATE_VERSION),
        profile=meta.get("profile"),
        configurable=bool(meta.get("configurable")),
        cells_per_section=meta.get("cells_per_section"),
        disconnector=dict(meta["disconnector"]) if isinstance(meta.get("disconnector"), dict) else None,
    )
    for index, entry in enumerate(entries, start=1):
        if _is_meta(entry):
            continue
        raw_cells = entry.get("cells")
        if not isinstance(raw_cells, list):
            continue
        cells = [cell for cell in raw_cells if isinstance(cell, dict)]
        if not cells:
            continue
        parsed.sections.append(
            SectionSpec(
                section_no=int(entry.get("section_no") or index),
                label=str(entry.get("label") or f"Секция {index}"),
                voltage_kv=entry.get("voltage_kv"),
                cells=[_normalize_cell_entry(cell) for cell in cells],
            )
        )
    return parsed


def _normalize_cell_entry(cell: dict[str, Any]) -> dict[str, Any]:
    kind = str(cell.get("cell_kind") or cell.get("kind") or "out").strip().lower()
    kind = CELL_KIND_BY_SCHEMA_ROLE.get(kind, kind)
    if kind not in CELL_KINDS:
        kind = "out"
    normalized = _cell_entry(
        kind,
        int(cell.get("count") or 1),
        str(cell.get("label") or "").strip() or None,
        voltage_kv=cell.get("voltage_kv"),
    )
    if cell.get("type_code"):
        normalized["type_code"] = str(cell["type_code"])
    return normalized


def _parse_plan_dict(raw: dict[str, Any]) -> ParsedTemplate:
    """Формат плана 31 §3.5: ``{"sections": [...], "cells": [...]}``."""
    parsed = ParsedTemplate(
        version=TEMPLATE_VERSION,
        profile=raw.get("profile"),
        configurable=bool(raw.get("configurable")),
        cells_per_section=raw.get("cells_per_section"),
    )
    sections = [item for item in (raw.get("sections") or []) if isinstance(item, dict)]
    top_cells = [item for item in (raw.get("cells") or []) if isinstance(item, dict)]
    if sections:
        for index, entry in enumerate(sections, start=1):
            own = [cell for cell in (entry.get("cells") or []) if isinstance(cell, dict)]
            cells = own or top_cells
            parsed.sections.append(
                SectionSpec(
                    section_no=int(entry.get("no") or entry.get("section_no") or index),
                    label=str(entry.get("label") or f"Секция {index}"),
                    voltage_kv=entry.get("voltage_kv"),
                    cells=[_normalize_cell_entry(cell) for cell in cells],
                )
            )
    elif top_cells:
        parsed.sections.append(
            SectionSpec(
                section_no=1,
                label="Секция 1",
                cells=[_normalize_cell_entry(cell) for cell in top_cells],
            )
        )
    if isinstance(raw.get("disconnector"), dict):
        parsed.disconnector = dict(raw["disconnector"])
    return parsed


def _parse_legacy_list(raw: list[Any]) -> ParsedTemplate:
    """Формат Спринта 21: ``[{"type_code": "cell", "count": 6, "label": "…"}]``."""
    parsed = ParsedTemplate(version=1, sections=[SectionSpec(section_no=1, label="Секция 1")])
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip() or "Ячейка"
        count = max(1, min(int(entry.get("count") or 1), 200))
        parsed.sections[0].cells.append(
            _cell_entry("out", count, label, voltage_kv=entry.get("voltage_kv"))
        )
        if entry.get("type_code"):
            parsed.sections[0].cells[-1]["type_code"] = str(entry["type_code"])
    return parsed


def parse_template(raw: Any) -> ParsedTemplate:
    """Разобрать любой поддерживаемый шаблон; пустой — ``ParsedTemplate()``."""
    if raw is None:
        return ParsedTemplate()
    if isinstance(raw, dict):
        return _parse_plan_dict(raw)
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, dict)]
        if not entries:
            return ParsedTemplate()
        v2 = _parse_v2_list(entries)
        if v2 is not None and (v2.sections or v2.disconnector):
            return v2
        return _parse_legacy_list(entries)
    return ParsedTemplate()


def build_layout(
    parsed: ParsedTemplate, *, cells_per_section: int | None = None
) -> list[CellBlueprint]:
    """Плоский упорядоченный список ячеек: секции по порядку, номера сквозные."""
    per_section = _normalize_cells_per_section(cells_per_section)

    if per_section is not None and not parsed.configurable:
        raise ApiError(
            422,
            "composite.not_configurable",
            "Для этого типа число ячеек фиксировано шаблоном",
            fields={"cells_per_section": "Тип не поддерживает настройку числа ячеек"},
        )

    sections = list(parsed.sections)
    if per_section is not None and parsed.configurable and parsed.profile == PROFILE_PS:
        rebuilt: list[SectionSpec] = []
        for section in sections:
            rebuilt.append(
                SectionSpec(
                    section_no=section.section_no,
                    label=section.label,
                    voltage_kv=section.voltage_kv,
                    cells=[
                        _cell_entry(kind, count, voltage_kv=section.voltage_kv or None)
                        for kind, count in _ps_section_cells(per_section)
                    ],
                )
            )
        sections = rebuilt

    blueprints: list[CellBlueprint] = []
    number = 0
    for section in sections:
        for cell in section.cells:
            kind = str(cell.get("cell_kind") or "out")
            count = max(1, int(cell.get("count") or 1))
            label = str(cell.get("label") or CELL_KIND_TITLES.get(kind, "Ячейка"))
            for _ in range(count):
                number += 1
                blueprints.append(
                    CellBlueprint(
                        cell_kind=kind,
                        section_no=section.section_no,
                        label=label,
                        voltage_kv=cell.get("voltage_kv") or section.voltage_kv,
                        type_code=cell.get("type_code"),
                    )
                )
    return blueprints


# --- профили и наполнение справочника ---------------------------------------


def profile_for_type(
    code: str | None, name: str | None, equipment_class: str | None = None
) -> str | None:
    """Определить профиль шаблона по коду/названию/классу типа.

    Порядок важен: «КТП (комплектная трансформаторная подстанция)» содержит
    слово «подстанция», поэтому КТП проверяется раньше ПС.
    """
    code_norm = (code or "").strip().lower()
    name_norm = (name or "").strip().lower()

    if code_norm in BKRU_CODES or "бкру" in name_norm:
        return PROFILE_BKRU
    if code_norm in KTP_CODES or "ктп" in name_norm:
        return PROFILE_KTP
    if code_norm in PS_CODES or "пс-" in name_norm or "пс " in name_norm or "подстанц" in name_norm:
        return PROFILE_PS
    return None


def _resolve_cell_type(db: Session, preferred: str | None = None) -> AssetType:
    """Тип ячейки: явный → стандартные коды → активный аналог."""
    candidates = [preferred] if preferred else []
    candidates += ["cell", "yacheyka", "tcell", "yach_1_f21k"]
    for code in candidates:
        asset_type = db.scalar(
            select(AssetType).where(AssetType.code == code, AssetType.is_active.is_(True))
        )
        if asset_type is not None:
            return asset_type
    fallback = db.scalar(
        select(AssetType)
        .where(
            AssetType.is_active.is_(True),
            or_(
                AssetType.equipment_class == "cell",
                AssetType.name.ilike("%ячейк%"),
                AssetType.code.ilike("%yach%"),
                AssetType.code.ilike("%cell%"),
            ),
        )
        .order_by(AssetType.sort_order)
    )
    if fallback is not None:
        return fallback
    raise ApiError(400, "composite.no_cell_type", "В справочнике нет активного типа ячейки")


def resolve_cell_type(db: Session, preferred: str | None = None) -> AssetType:
    return _resolve_cell_type(db, preferred)


def resolve_disconnector_type(db: Session) -> AssetType:
    """Коммутационный аппарат для вводного разъединителя КТП."""
    for code in (DISCONNECTOR_TYPE_SPEC["code"], "ruBilnik", "rubilnik"):
        asset_type = db.scalar(
            select(AssetType).where(AssetType.code == code, AssetType.is_active.is_(True))
        )
        if asset_type is not None:
            return asset_type
    fallback = db.scalar(
        select(AssetType)
        .where(
            AssetType.is_active.is_(True),
            or_(
                AssetType.equipment_class == "switching",
                AssetType.name.ilike("%разъедин%"),
                AssetType.code.ilike("%razed%"),
            ),
        )
        .order_by(AssetType.sort_order)
    )
    if fallback is not None:
        return fallback
    return ensure_disconnector_type(db)


def ensure_disconnector_type(db: Session) -> AssetType:
    """Создать тип «Разъединитель» (класс switching), если его нет."""
    from app.services import asset_fields  # локальный импорт: asset_fields не зависит от нас

    asset_type = db.scalar(
        select(AssetType).where(AssetType.code == DISCONNECTOR_TYPE_SPEC["code"])
    )
    if asset_type is not None:
        if not asset_type.is_active:
            asset_type.is_active = True
        if (asset_type.equipment_class or "equipment") == "equipment":
            asset_type.equipment_class = "switching"
        if not asset_type.group_code:
            asset_type.group_code = "switching"
        db.flush()
        return asset_type

    asset_type = AssetType(
        id=uuid.uuid4(),
        code=DISCONNECTOR_TYPE_SPEC["code"],
        name=DISCONNECTOR_TYPE_SPEC["name"],
        category=DISCONNECTOR_TYPE_SPEC["category"],
        equipment_class=DISCONNECTOR_TYPE_SPEC["equipment_class"],
        group_code=DISCONNECTOR_TYPE_SPEC["group_code"],
        icon=DISCONNECTOR_TYPE_SPEC["icon"],
        color=DISCONNECTOR_TYPE_SPEC["color"],
        schema_symbol=DISCONNECTOR_TYPE_SPEC["schema_symbol"],
        sort_order=DISCONNECTOR_TYPE_SPEC["sort_order"],
        port_template=DISCONNECTOR_TYPE_SPEC["port_template"],
        attr_schema=DISCONNECTOR_TYPE_SPEC["attr_schema"],
        required_attrs=list(DISCONNECTOR_TYPE_SPEC["required_attrs"]),
        is_mobile_default=False,
        is_active=True,
    )
    db.add(asset_type)
    db.flush()
    asset_fields.sync_from_schema(db, asset_type)
    return asset_type


def seed_type_templates(db: Session) -> dict[str, int]:
    """Идемпотентно проставить v2-шаблоны типам БКРУ/ПС/КТП.

    Уже настроенный админом v2-шаблон (``version >= 2``) не перезаписывается:
    сид добирает только пустые и устаревшие (v1) значения.
    """
    counts = {"templates": 0, "disconnector_type": 0}
    existed = db.scalar(
        select(AssetType.id).where(AssetType.code == DISCONNECTOR_TYPE_SPEC["code"])
    )
    ensure_disconnector_type(db)
    counts["disconnector_type"] = 0 if existed is not None else 1

    for asset_type in db.scalars(select(AssetType)).all():
        profile = profile_for_type(asset_type.code, asset_type.name, asset_type.equipment_class)
        if profile is None:
            continue
        current = parse_template(asset_type.composite_template)
        if current.is_v2 and not current.empty:
            continue
        asset_type.composite_template = builtin_template(profile)
        asset_type.is_composite = True
        counts["templates"] += 1
    db.flush()
    return counts


def templates_summary(templates: Any) -> str:
    """Короткая человекочитаемая подпись состава — для аудита/отчёта."""
    parsed = parse_template(templates)
    if parsed.empty:
        return "состав не задан"
    parts = []
    for section in parsed.sections:
        total = sum(int(cell.get("count") or 1) for cell in section.cells)
        parts.append(f"секция {section.section_no}: {total} яч.")
    if parsed.disconnector:
        parts.append("вводной разъединитель")
    return ", ".join(parts)
