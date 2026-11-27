"""Группировка объектов: подтипы собираются в родительский объект (ПС).

Родитель ведёт себя как блок схемы: на карте видна одна иконка, на схеме —
рамка с подписью и дочерними объектами внутри.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict, not_found
from app.models import Asset, AssetPort, Employee
from app.schemas.gis import AssetCreate, AssetGroupIn
from app.services import audit, gis


def _port(asset: Asset, code: str) -> AssetPort | None:
    return next((port for port in asset.ports if port.code == code), None)


def create_group(db: Session, actor: Employee, payload: AssetGroupIn) -> Asset:
    parent_type = db.scalar(
        select(__import__("app.models", fromlist=["AssetType"]).AssetType).where(
            __import__("app.models", fromlist=["AssetType"]).AssetType.code == payload.parent_type_code
        )
    )
    if parent_type is None:
        raise not_found("Тип родительского объекта не найден")

    children: list[Asset] = []
    for child_id in payload.child_ids:
        child = db.get(Asset, child_id)
        if child is None or child.deleted_at is not None:
            raise not_found(f"Объект {child_id} не найден")
        if child.schema_block_id is not None:
            raise conflict(
                f"Объект «{child.name}» уже входит в группу",
                "group.child_already_grouped",
            )
        children.append(child)

    if not children:
        raise ApiError(400, "group.empty", "Не выбрано ни одного объекта")

    pit = gis.get_pit(db)
    parent = gis.create_asset(
        db,
        AssetCreate(
            name=payload.name[:255],
            type_code=parent_type.code,
            x=payload.x if payload.x is not None else 100,
            y=payload.y if payload.y is not None else 100,
            status="on",
        ),
        actor=actor,
    )
    parent.schema_role = "block"
    parent.attrs = {**(parent.attrs or {}), "block_code": "group", "group": True}

    for code, label, kind in (("IN-1", "Ввод", "in"), ("OUT-1", "Выход", "out")):
        if _port(parent, code) is None:
            db.add(
                AssetPort(
                    id=uuid.uuid4(),
                    asset_id=parent.id,
                    code=code,
                    name=label,
                    kind=kind,
                    sort_order=0,
                )
            )

    for index, child in enumerate(children):
        child.parent_asset_id = parent.id
        child.schema_block_id = parent.id
        if not child.schema_role:
            child.schema_role = "outgoing" if child.asset_type.category in ("equipment", "mobile") else "cell"
        child.schema_local_x = 40 + (index % 4) * 120
        child.schema_local_y = 60 + (index // 4) * 90

    db.commit()
    db.refresh(parent)
    audit.add(
        "asset.grouped",
        entity="asset",
        entity_id=parent.id,
        detail=f"Собрана группа «{parent.name}»: {len(children)} объектов",
        payload={"children": [str(child.id) for child in children]},
    )
    return parent


def ungroup(db: Session, parent: Asset, actor: Employee) -> int:
    if parent.schema_block_id is not None:
        raise ApiError(400, "group.child", "Объект сам входит в группу")
    children = [
        child
        for child in db.scalars(
            select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
        ).all()
    ]
    if not children:
        raise conflict("У объекта нет дочерних элементов", "group.empty")

    for child in children:
        child.schema_block_id = None
        child.parent_asset_id = None
        child.schema_role = None
        child.schema_local_x = None
        child.schema_local_y = None

    gis.soft_delete(db, parent, actor=actor)
    audit.add(
        "asset.ungrouped",
        entity="asset",
        entity_id=parent.id,
        detail=f"Группа «{parent.name}» разъединена: {len(children)} объектов",
    )
    return len(children)
