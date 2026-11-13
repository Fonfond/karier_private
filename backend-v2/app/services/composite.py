"""Комплектное оборудование: размещение типа с дочерними ячейками."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict, not_found
from app.models import Asset, AssetPort, AssetType, Employee
from app.schemas.gis import AssetCreate
from app.services import audit, gis


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


def _layout(index: int) -> tuple[float, float]:
    return (40 + (index % 3) * 150, 60 + (index // 3) * 96)


def place(
    db: Session,
    actor: Employee,
    *,
    type_id: uuid.UUID,
    x: float,
    y: float,
    name: str | None = None,
) -> dict[str, Any]:
    asset_type = db.get(AssetType, type_id)
    if asset_type is None:
        raise not_found("Тип не найден")
    if not asset_type.is_composite:
        raise conflict("Тип не помечен как комплектное оборудование", "composite.not_composite")

    template = list(asset_type.composite_template or [])
    if not template:
        raise conflict("В типе не задан состав (ячейки)", "composite.empty_template")

    parent = gis.create_asset(
        db,
        AssetCreate(
            name=(name or asset_type.name)[:255],
            type_code=asset_type.code,
            x=x,
            y=y,
            status="on",
        ),
        actor=actor,
    )
    parent.schema_role = "block"
    parent.attrs = {
        **(parent.attrs or {}),
        "block_code": asset_type.code,
        "composite": True,
    }
    _add_port(db, parent, "IN-1", "Ввод", "in")
    _add_port(db, parent, "OUT-1", "Выход", "out")

    children: list[Asset] = []
    index = 0
    for entry in template:
        if not isinstance(entry, dict):
            continue
        child_code = str(entry.get("type_code") or "").strip()
        count = max(1, min(int(entry.get("count") or 1), 64))
        label = str(entry.get("label") or "").strip()
        child_type = db.scalar(select(AssetType).where(AssetType.code == child_code))
        if child_type is None:
            continue
        for number in range(1, count + 1):
            child_name = label or child_type.name
            if count > 1 or label:
                child_name = f"{child_name} {number}".strip()
            child = gis.create_asset(
                db,
                AssetCreate(
                    name=child_name[:255],
                    type_code=child_type.code,
                    status="on",
                ),
                actor=actor,
            )
            child.parent_asset_id = parent.id
            child.schema_block_id = parent.id
            child.schema_role = "cell"
            local_x, local_y = _layout(index)
            child.schema_local_x = local_x
            child.schema_local_y = local_y
            children.append(child)
            index += 1

    if not children:
        raise conflict("Не удалось создать ячейки: проверьте состав в типе", "composite.no_children")

    db.commit()
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
