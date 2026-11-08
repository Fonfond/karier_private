"""Библиотека блоков схемы: установка шаблона, ячейки, защита структуры."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict, not_found
from app.models import Asset, AssetType, Employee, Link, SchemaBlock
from app.schemas.gis import AssetCreate
from app.services import audit, gis, links as links_service

STRUCTURAL_ROLES = {
    "busbar",
    "transformer",
    "tt",
    "opn",
    "znv",
    "section",
    "input",
}


def list_blocks(db: Session) -> list[SchemaBlock]:
    return list(
        db.scalars(
            select(SchemaBlock)
            .where(SchemaBlock.is_active.is_(True))
            .order_by(SchemaBlock.sort_order, SchemaBlock.name)
        )
    )


def get_block(db: Session, code: str) -> SchemaBlock:
    block = db.scalar(select(SchemaBlock).where(SchemaBlock.code == code))
    if block is None:
        raise not_found("Блок схемы не найден")
    return block


def _type_by_code(db: Session, code: str) -> AssetType | None:
    return db.scalar(select(AssetType).where(AssetType.code == code, AssetType.is_active.is_(True)))


def _create_child(
    db: Session,
    *,
    parent: Asset,
    node: dict[str, Any],
    actor: Employee,
    code_suffix: str,
) -> Asset:
    type_code = node.get("type_code") or "cell"
    asset_type = _type_by_code(db, type_code)
    if asset_type is None:
        raise ApiError(400, "block.unknown_type", f"Нет типа {type_code} для блока")

    asset = gis.create_asset(
        db,
        AssetCreate(
            name=node.get("label") or node.get("key") or code_suffix,
            type_code=type_code,
            code=code_suffix,
            status="on" if node.get("role") != "load" else "off",
            parent_id=parent.id,
        ),
        actor=actor,
    )
    asset.schema_block_id = parent.id
    asset.schema_role = node.get("role", "cell")
    asset.schema_local_x = node.get("x", 0)
    asset.schema_local_y = node.get("y", 0)
    params = node.get("params") or {}
    if params:
        asset.attrs = {**(asset.attrs or {}), **params}
    db.commit()
    db.refresh(asset)
    return asset


def instantiate(
    db: Session,
    block: SchemaBlock,
    actor: Employee,
    *,
    x: float,
    y: float,
    name: str | None = None,
) -> dict[str, Any]:
    """Создать объект-блок и все вложенные элементы по шаблону."""
    if block.asset_type is None:
        raise ApiError(400, "block.no_type", "У блока не задан тип объекта")

    template = block.template_json or {}
    nodes = template.get("nodes") or []
    if not nodes:
        raise ApiError(400, "block.empty", "Шаблон блока пуст")

    parent = gis.create_asset(
        db,
        AssetCreate(
            name=(name or block.name)[:255],
            type_code=block.asset_type.code,
            x=x,
            y=y,
            status="on",
        ),
        actor=actor,
    )

    created: dict[str, Asset] = {}
    for node in nodes:
        key = str(node.get("key") or uuid.uuid4().hex[:6])
        child = _create_child(
            db, parent=parent, node=node, actor=actor, code_suffix=f"{parent.code}-{key}"[:64]
        )
        created[key] = child

    # связи внутри блока: from → to по первым подходящим портам
    for pair in template.get("links") or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        source, target = created.get(str(pair[0])), created.get(str(pair[1]))
        if source is None or target is None:
            continue
        try:
            links_service.create_link(
                db,
                parent.pit_id,
                __import__("app.schemas.gis", fromlist=["LinkCreate"]).LinkCreate(
                    from_port_id=_port(source, "out"),
                    to_port_id=_port(target, "in"),
                    link_type="internal",
                ),
                actor=actor,
            )
        except ApiError:
            continue

    # внешние порты блока: недостающие создаём, существующие обновляем
    from app.models import AssetPort

    existing = {port.code: port for port in parent.ports}
    for spec in template.get("external_ports") or []:
        code = str(spec.get("code"))[:24]
        port = existing.get(code)
        if port is None:
            port = AssetPort(
                id=uuid.uuid4(),
                asset_id=parent.id,
                code=code,
                name=str(spec.get("label") or code)[:64],
                kind=spec.get("kind", "out"),
                nominal_voltage_kv=spec.get("voltage_kv"),
                sort_order=int(spec.get("sort_order") or 0),
            )
            db.add(port)
        else:
            port.name = str(spec.get("label") or code)[:64]
            port.kind = spec.get("kind", port.kind)
            port.nominal_voltage_kv = spec.get("voltage_kv") or port.nominal_voltage_kv
    parent.schema_role = "block"
    db.commit()

    audit.add(
        "schema.block_instantiated",
        entity="asset",
        entity_id=parent.id,
        detail=f"Установлен блок «{block.name}»: элементов {len(created)}",
        payload={"block": block.code, "children": len(created)},
    )
    return {
        "asset_id": str(parent.id),
        "code": parent.code,
        "children": len(created),
        "block_code": block.code,
    }


def _port(asset: Asset, kind: str):
    for port in asset.ports:
        if port.kind == kind or port.kind == "io":
            return port.id
    for port in asset.ports:
        return port.id
    raise ApiError(400, "block.no_ports", f"У объекта {asset.code} нет портов")


def _delete_links_of(db: Session, asset: Asset, actor: Employee) -> None:
    port_ids = {port.id for port in asset.ports}
    if not port_ids:
        return
    rows = db.scalars(
        select(Link).where(
            or_(Link.from_port_id.in_(port_ids), Link.to_port_id.in_(port_ids))
        )
    ).all()
    for link in rows:
        links_service.delete_link(db, link, actor=actor)


def add_cell(
    db: Session,
    parent: Asset,
    actor: Employee,
    *,
    label: str,
    params: dict[str, Any] | None = None,
    role: str = "cell",
    type_code: str = "cell",
) -> Asset:
    if parent.schema_role not in ("block", None):
        raise ApiError(400, "block.not_block", "Объект не является блоком схемы")
    if role in STRUCTURAL_ROLES:
        raise ApiError(400, "block.structural_role", "Нельзя добавить структурный элемент вручную")

    siblings = db.scalars(
        select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
    ).all()
    max_x = max([float(item.schema_local_x or 0) for item in siblings] or [0])
    node = {
        "key": f"cell{uuid.uuid4().hex[:4]}",
        "role": role,
        "label": label,
        "type_code": type_code,
        "x": max_x + 120,
        "y": 220,
        "params": params or {},
    }
    child = _create_child(
        db, parent=parent, node=node, actor=actor, code_suffix=f"{parent.code}-{node['key']}"[:64]
    )
    audit.add(
        "schema.cell_added",
        entity="asset",
        entity_id=child.id,
        detail=f"В блок {parent.code} добавлена ячейка {label}",
    )
    return child


def remove_cell(db: Session, parent: Asset, cell: Asset, actor: Employee) -> None:
    if cell.schema_block_id != parent.id:
        raise ApiError(400, "block.foreign_cell", "Ячейка принадлежит другому блоку")
    if (cell.schema_role or "cell") in STRUCTURAL_ROLES:
        raise conflict(
            "Это структурный элемент блока (шина, ввод, ТТ, ОПН) — удалить нельзя",
            "block.structural_protected",
        )
    remaining = db.scalar(
        select(func.count(Asset.id)).where(
            Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None)
        )
    ) or 0
    if remaining <= 1:
        raise conflict("Нельзя удалить последнюю ячейку блока", "block.last_cell")

    _delete_links_of(db, cell, actor)
    gis.soft_delete(db, cell, actor=actor)
    audit.add(
        "schema.cell_removed",
        entity="asset",
        entity_id=cell.id,
        detail=f"Из блока {parent.code} удалена ячейка {cell.code}",
    )


def block_summary(db: Session, block: SchemaBlock) -> dict[str, Any]:
    template = block.template_json or {}
    nodes = template.get("nodes") or []
    return {
        "id": block.id,
        "code": block.code,
        "name": block.name,
        "block_type": block.block_type,
        "icon": block.icon,
        "asset_type_code": block.asset_type.code if block.asset_type else None,
        "nodes_count": len(nodes),
        "external_ports": len(template.get("external_ports") or []),
        "roles": sorted({str(node.get("role")) for node in nodes}),
    }
