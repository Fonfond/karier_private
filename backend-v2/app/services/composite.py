"""Комплектное оборудование: размещение типа с дочерними ячейками.

Спринт 21 создавал комплект по «плоскому» шаблону v1 (``type_code``/``count``).
Этап 2 добавил шаблон v2 (секции, вводные/отходящие/секционные ячейки, КТП с
вводным разъединителем) и атомарный вызов ``POST /api/schema/composite``.
Старые ``POST /api/composites/place`` и ``/attach`` продолжают работать на обоих
форматах: разбор шаблона общий (``app.services.equipment_templates``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.models import Asset, AssetPort, AssetType, Employee
from app.schemas.gis import AssetCreate
from app.services import audit, gis
from app.services import equipment_templates as templates

#: Раскладка ячеек внутри блока (пиксели холста схемы).
LAYOUT_COLUMNS = 6
LAYOUT_X0 = 60
LAYOUT_Y0 = 140
LAYOUT_DX = 120
LAYOUT_DY = 96


def _layout(index: int) -> tuple[float, float]:
    return (
        LAYOUT_X0 + (index % LAYOUT_COLUMNS) * LAYOUT_DX,
        LAYOUT_Y0 + (index // LAYOUT_COLUMNS) * LAYOUT_DY,
    )


def _port(asset: Asset, code: str) -> AssetPort | None:
    return next((p for p in asset.ports if p.code == code), None)


def _add_port(db: Session, asset: Asset, code: str, name: str, kind: str) -> None:
    if _port(asset, code) is None:
        db.add(
            AssetPort(
                id=uuid.uuid4(),
                asset_id=asset.id,
                code=code,
                name=name,
                kind=kind,
                sort_order=0,
            )
        )


def effective_template(asset_type: AssetType) -> templates.ParsedTemplate:
    """Шаблон типа: сохранённый v2 → встроенный профиль → legacy v1.

    Встроенный профиль нужен, если мигратор/сид ещё не разметил тип (например,
    демо-данные залили поверх схемы): БКРУ/ПС/КТП работают сразу.
    """
    parsed = templates.parse_template(asset_type.composite_template)
    if parsed.is_v2 and not parsed.empty:
        return parsed
    profile = templates.profile_for_type(
        asset_type.code, asset_type.name, asset_type.equipment_class
    )
    if profile is not None:
        return templates.parse_template(templates.builtin_template(profile))
    return parsed


def _cell_name(blueprint: templates.CellBlueprint, number: int) -> str:
    title = templates.CELL_KIND_TITLES.get(blueprint.cell_kind, "Ячейка")
    label = (blueprint.label or "").strip()
    if label and label.lower() not in {title.lower(), "ячейка"}:
        return f"Яч. №{number} ({label})"[:255]
    return f"Яч. №{number} ({title})"[:255]


def _create_cells(
    db: Session,
    parent: Asset,
    actor: Employee,
    blueprints: list[templates.CellBlueprint],
) -> list[Asset]:
    """Создать ячейки в порядке шаблона (одна транзакция с блоком)."""
    cells: list[Asset] = []
    type_cache: dict[str | None, AssetType] = {}
    for index, blueprint in enumerate(blueprints):
        key = blueprint.type_code
        if key not in type_cache:
            type_cache[key] = templates.resolve_cell_type(db, blueprint.type_code)
        cell_type = type_cache[key]
        number = index + 1
        section_label = f"Секция {blueprint.section_no}"
        attrs: dict[str, Any] = {
            "composite": True,
            "cell_kind": blueprint.cell_kind,
            "cell_title": templates.CELL_KIND_TITLES[blueprint.cell_kind],
            "section_no": blueprint.section_no,
            "section": section_label,
        }
        if blueprint.voltage_kv is not None:
            attrs["voltage_kv"] = float(blueprint.voltage_kv)
        cell = gis.create_asset(
            db,
            AssetCreate(
                name=_cell_name(blueprint, number),
                type_code=cell_type.code,
                status="off",
                parent_id=parent.id,
                attrs=attrs,
                cell_kind=blueprint.cell_kind,
                cell_no=number,
                section_no=blueprint.section_no,
            ),
            actor=actor,
            # Ячейка — визуальный элемент схемы: паспортные поля типа не требуем.
            validate_attributes=False,
            commit=False,
        )
        cell.schema_block_id = parent.id
        cell.schema_role = templates.SCHEMA_ROLE_BY_CELL_KIND.get(blueprint.cell_kind, "cell")
        local_x, local_y = _layout(index)
        cell.schema_local_x = local_x
        cell.schema_local_y = local_y
        cells.append(cell)
    return cells


def _create_disconnector(
    db: Session, parent: Asset, actor: Employee, spec: dict[str, Any]
) -> Asset:
    """Вводной разъединитель КТП: дочерний объект класса switching, cell_kind=in."""
    asset_type = templates.resolve_disconnector_type(db)
    voltage = spec.get("voltage_kv")
    attrs: dict[str, Any] = {
        "composite": True,
        "cell_kind": "in",
        "role": "disconnector",
        "disconnector": True,
    }
    if voltage is not None:
        attrs["voltage_kv"] = float(voltage)
    child = gis.create_asset(
        db,
        AssetCreate(
            name=str(spec.get("label") or "Вводной разъединитель")[:255],
            type_code=asset_type.code,
            status="off",
            parent_id=parent.id,
            attrs=attrs,
            cell_kind="in",
        ),
        actor=actor,
        validate_attributes=False,
        commit=False,
    )
    child.schema_block_id = parent.id
    child.schema_role = "incoming"
    child.schema_local_x = LAYOUT_X0
    child.schema_local_y = LAYOUT_Y0 - LAYOUT_DY
    return child


def _compose(
    db: Session,
    asset_type: AssetType,
    actor: Employee,
    *,
    name: str | None,
    x: float | None,
    y: float | None,
    cells_per_section: int | None = None,
    code: str | None = None,
    schema_placement: bool = False,
) -> dict[str, Any]:
    """Создать блок, ячейки и разъединитель одной транзакцией."""
    parsed = effective_template(asset_type)
    if parsed.empty:
        raise conflict("В типе не задан состав (ячейки)", "composite.empty_template")

    blueprints = templates.build_layout(parsed, cells_per_section=cells_per_section)
    if not blueprints and parsed.disconnector is None:
        raise conflict(
            "Шаблон не создаёт ни одной ячейки: проверьте состав в типе",
            "composite.no_children",
        )

    block_attrs: dict[str, Any] = {
        "block_code": asset_type.code,
        "composite": True,
        "template_version": templates.TEMPLATE_VERSION if parsed.is_v2 else 1,
    }
    if parsed.profile:
        block_attrs["composite_profile"] = parsed.profile
    if cells_per_section is not None:
        block_attrs["cells_per_section"] = int(cells_per_section)
    elif parsed.cells_per_section is not None:
        block_attrs["cells_per_section"] = int(parsed.cells_per_section)

    parent = gis.create_asset(
        db,
        AssetCreate(
            name=(name or asset_type.name)[:255],
            type_code=asset_type.code,
            code=code,
            status="on",
            # Старый /composites/place ставил объект в метры карты (x, y);
            # новый /schema/composite — в пиксели схемы (schema_x, schema_y).
            x=None if schema_placement else x,
            y=None if schema_placement else y,
            attrs=block_attrs,
        ),
        actor=actor,
        validate_attributes=False,
        commit=False,
    )
    parent.schema_role = "block"
    if schema_placement:
        parent.schema_x = x
        parent.schema_y = y
    _add_port(db, parent, "IN-1", "Ввод", "in")
    _add_port(db, parent, "OUT-1", "Выход", "out")
    db.flush()

    cells = _create_cells(db, parent, actor, blueprints) if blueprints else []
    disconnector = (
        _create_disconnector(db, parent, actor, parsed.disconnector)
        if parsed.disconnector is not None
        else None
    )
    db.commit()
    db.refresh(parent)
    for child in cells:
        db.refresh(child)
    if disconnector is not None:
        db.refresh(disconnector)

    sections: list[dict[str, Any]] = []
    if cells:
        by_section: dict[int, list[Asset]] = {}
        for cell in cells:
            by_section.setdefault(int(cell.section_no or 1), []).append(cell)
        parsed_labels = {section.section_no: section.label for section in parsed.sections}
        parsed_voltage = {section.section_no: section.voltage_kv for section in parsed.sections}
        for section_no in sorted(by_section):
            section_cells = by_section[section_no]
            voltage = section_cells[0].attrs.get("voltage_kv") if section_cells else None
            sections.append(
                {
                    "section_no": section_no,
                    "label": parsed_labels.get(section_no) or f"Секция {section_no}",
                    "voltage_kv": float(voltage)
                    if voltage is not None
                    else parsed_voltage.get(section_no),
                    "cells": section_cells,
                }
            )

    return {
        "parent": parent,
        "cells": cells,
        "sections": sections,
        "disconnector": disconnector,
        "template": parsed,
    }


def compose(
    db: Session,
    actor: Employee,
    *,
    type_code: str,
    name: str | None = None,
    x: float,
    y: float,
    cells_per_section: int | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """Этап 2: атомарно создать блок + ячейки (+ разъединитель КТП) на схеме."""
    asset_type = gis.get_type(db, type_code)
    if not asset_type.is_composite:
        # Тип ещё не размечен как комплектный (старые данные) — но профиль
        # БКРУ/ПС/КТП известен: разрешаем, иначе мастер этапа 2 бесполезен.
        profile = templates.profile_for_type(
            asset_type.code, asset_type.name, asset_type.equipment_class
        )
        if profile is None:
            raise conflict("Тип не помечен как комплектное оборудование", "composite.not_composite")
    result = _compose(
        db,
        asset_type,
        actor,
        name=name,
        x=x,
        y=y,
        cells_per_section=cells_per_section,
        code=code,
        schema_placement=True,
    )
    parent = result["parent"]
    children = list(result["cells"])
    if result["disconnector"] is not None:
        children.append(result["disconnector"])
    audit.add(
        "composite.composed",
        entity="asset",
        entity_id=parent.id,
        detail=(
            f"Создан блок «{parent.name}» ({asset_type.code}): "
            f"{len(result['cells'])} яч."
            + (", вводной разъединитель" if result["disconnector"] is not None else "")
        ),
        payload={
            "type_code": asset_type.code,
            "cells": [str(cell.id) for cell in result["cells"]],
            "sections": len(result["sections"]),
            "disconnector_id": str(result["disconnector"].id)
            if result["disconnector"] is not None
            else None,
            "cells_per_section": cells_per_section,
        },
    )
    return {**result, "children": len(children)}


def place(
    db: Session,
    actor: Employee,
    *,
    type_id: uuid.UUID,
    x: float,
    y: float,
    name: str | None = None,
) -> dict[str, Any]:
    """Совместимость Спринта 21: разместить комплект по id типа."""
    asset_type = db.get(AssetType, type_id)
    if asset_type is None:
        raise not_found("Тип не найден")
    if not asset_type.is_composite:
        profile = templates.profile_for_type(
            asset_type.code, asset_type.name, asset_type.equipment_class
        )
        if profile is None:
            raise conflict("Тип не помечен как комплектное оборудование", "composite.not_composite")

    result = _compose(
        db,
        asset_type,
        actor,
        name=name,
        x=x,
        y=y,
        schema_placement=False,
    )
    parent = result["parent"]
    children = list(result["cells"])
    if result["disconnector"] is not None:
        children.append(result["disconnector"])

    audit.add(
        "composite.placed",
        entity="asset",
        entity_id=parent.id,
        detail=f"Размещён комплект «{parent.name}»: {len(children)} ячеек",
        payload={"children": [str(child.id) for child in children]},
    )
    return {"id": parent.id, "name": parent.name, "code": parent.code, "children": len(children)}


def attach(db: Session, actor: Employee, parent: Asset, child_ids: list[uuid.UUID]) -> dict[str, Any]:
    if not parent.asset_type.is_composite:
        raise conflict("Объект не является комплектным оборудованием", "composite.not_composite")
    children = []
    for child_id in child_ids:
        child = db.get(Asset, child_id)
        if child is None or child.deleted_at is not None:
            raise not_found("Объект не найден")
        if child.schema_block_id not in (None, parent.id):
            raise conflict(f"«{child.name}» уже входит в другой комплект", "composite.child_grouped")
        children.append(child)

    existing = len(
        db.scalars(
            select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
        ).all()
    )
    for index, child in enumerate(children, start=existing):
        child.parent_asset_id = parent.id
        child.schema_block_id = parent.id
        child.schema_role = child.schema_role or "cell"
        local_x, local_y = _layout(index)
        child.schema_local_x = local_x
        child.schema_local_y = local_y
    db.commit()
    audit.add(
        "composite.attached",
        entity="asset",
        entity_id=parent.id,
        detail=f"В комплект «{parent.name}» добавлено ячеек: {len(children)}",
        payload={"children": [str(child.id) for child in children]},
    )
    return {
        "id": parent.id,
        "name": parent.name,
        "code": parent.code,
        "children": existing + len(children),
    }
