"""Библиотека блоков схемы: установка шаблона, ячейки, защита структуры."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict, not_found
from app.models import Asset, AssetPort, AssetType, Employee, Line, Link, SchemaBlock
from app.schemas.gis import AssetCreate, LinkCreate
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


def _prune_ports(db: Session, asset: Asset, specs: list[dict]) -> None:
    allowed = {str(spec.get("code"))[:24] for spec in specs}
    for port in list(asset.ports):
        if port.code not in allowed:
            db.delete(port)


def _create_child(
    db: Session,
    *,
    parent: Asset,
    node: dict[str, Any],
    actor: Employee,
    code_suffix: str,
) -> Asset:
    requested_type = node.get("type_code") or "cell"
    asset_type = _resolve_type(db, requested_type)

    asset = gis.create_asset(
        db,
        AssetCreate(
            name=node.get("label") or node.get("key") or code_suffix,
            type_code=asset_type.code,
            code=code_suffix,
            status="on" if node.get("role") != "load" else "off",
            parent_id=parent.id,
            attrs=dict(node.get("params") or {}),
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

    base_attrs: dict[str, Any] = {}
    if block.block_type == "simple":
        base_attrs = dict(nodes[0].get("params") or {})
        for attr in block.asset_type.required_attrs or []:
            schema = (block.asset_type.attr_schema or {}).get(attr) or {}
            if attr not in base_attrs:
                base_attrs[attr] = 0 if schema.get("type") == "number" else ""

    parent = gis.create_asset(
        db,
        AssetCreate(
            name=(name or block.name)[:255],
            type_code=block.asset_type.code,
            x=x,
            y=y,
            status="on",
            attrs=base_attrs,
        ),
        actor=actor,
    )

    if block.block_type == "simple":
        parent.attrs = {
            **base_attrs,
            **(parent.attrs or {}),
            "label": (name or block.name),
            "pole_no": (name or block.name) if block.asset_type.code == "pole" else None,
            "simple_block": block.code,
        }
        db.commit()
        existing_ports = {port.code: port for port in parent.ports}
        for spec in (template.get("external_ports") or []):
            code = str(spec.get("code"))[:24]
            if code in existing_ports:
                port = existing_ports[code]
                port.name = str(spec.get("label") or code)[:64]
                port.nominal_voltage_kv = spec.get("voltage_kv") or port.nominal_voltage_kv
                continue
            db.add(__import__("app.models", fromlist=["AssetPort"]).AssetPort(
                id=uuid.uuid4(), asset_id=parent.id, code=code,
                name=str(spec.get("label") or code)[:64],
                kind=spec.get("kind", "out"), nominal_voltage_kv=spec.get("voltage_kv"),
            ))
        db.flush()
        _prune_ports(db, parent, template.get("external_ports") or [])
        parent.schema_role = "block"
        db.commit()
        audit.add("schema.block_instantiated", entity="asset", entity_id=parent.id,
                  detail=f"Установлен простой блок «{block.name}»", payload={"block": block.code})
        return {"asset_id": str(parent.id), "code": parent.code, "children": 0, "block_code": block.code}

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
    _prune_ports(db, parent, template.get("external_ports") or [])
    parent.schema_role = "block"
    parent.attrs = {**(parent.attrs or {}), "block_code": block.code}
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


def _resolve_type(db: Session, code: str | None) -> AssetType:
    """Тип для ячейки: явный → стандартные коды → активный аналог «ячейки».

    В рабочей базе после «чистого листа» нет типа `cell`, поэтому слепое
    `type_code="cell"` ломалось бы. Лучше подобрать активный аналог, чем падать.
    """
    candidates = [code] if code else []
    candidates += ["cell", "yacheyka", "tcell", "yach"]
    for candidate in candidates:
        asset_type = _type_by_code(db, candidate)
        if asset_type is not None:
            return asset_type

    fallback = db.scalar(
        select(AssetType)
        .where(
            AssetType.is_active.is_(True),
            or_(
                AssetType.name.ilike("%ячейк%"),
                AssetType.code.ilike("%yach%"),
                AssetType.code.ilike("%cell%"),
            ),
        )
        .order_by(AssetType.sort_order)
    )
    if fallback is not None:
        return fallback

    fallback = db.scalar(
        select(AssetType)
        .where(AssetType.is_active.is_(True), AssetType.is_composite.is_(False))
        .order_by(AssetType.sort_order)
    )
    if fallback is not None:
        return fallback

    raise ApiError(400, "block.no_type", "В справочнике нет активного типа для ячейки")


def create_contour(
    db: Session,
    *,
    name: str,
    type_code: str,
    x: float,
    y: float,
    width: float,
    height: float,
    comment: str | None,
    actor: Employee,
) -> Asset:
    """Создать прямоугольный контур: объект в реестре + блок на схеме."""
    attrs: dict[str, Any] = {
        "block_code": "contour",
        "contour_w": float(width),
        "contour_h": float(height),
    }
    if comment:
        attrs["comment"] = comment

    asset = gis.create_asset(
        db,
        AssetCreate(name=name, type_code=type_code, attrs=attrs),
        actor=actor,
    )
    asset.schema_role = "block"
    asset.schema_x = x
    asset.schema_y = y
    db.commit()
    db.refresh(asset)

    audit.add(
        "schema.contour_created",
        entity="asset",
        entity_id=asset.id,
        detail=f"На схеме создан контур «{asset.name}» ({asset.code})",
    )
    return asset


def unplace_from_schema(db: Session, asset: Asset, *, actor: Employee) -> Asset:
    """Убрать объект со схемы, оставив его в реестре (отмена постановки)."""
    asset.schema_x = None
    asset.schema_y = None
    asset.version = (asset.version or 1) + 1
    db.commit()
    db.refresh(asset)

    audit.add(
        "schema.asset_unplaced",
        entity="asset",
        entity_id=asset.id,
        detail=f"Объект {asset.code} ({asset.name}) убран со схемы",
    )
    return asset

def place_on_schema(db: Session, asset: Asset, *, x: float, y: float, actor: Employee) -> Asset:
    """Поставить существующий объект реестра на схему — без создания дубля."""
    asset.schema_x = x
    asset.schema_y = y
    asset.version = (asset.version or 1) + 1
    db.commit()
    db.refresh(asset)

    audit.add(
        "schema.asset_placed",
        entity="asset",
        entity_id=asset.id,
        detail=f"Объект {asset.code} ({asset.name}) поставлен на схему",
    )
    return asset

def add_cell(
    db: Session,
    parent: Asset,
    actor: Employee,
    *,
    label: str,
    params: dict[str, Any] | None = None,
    role: str = "cell",
    type_code: str | None = None,
    x: float | None = None,
    y: float | None = None,
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
        "type_code": type_code or "cell",
        "x": float(x) if x is not None else max_x + 120,
        "y": float(y) if y is not None else 220,
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
    # У библиотечных блоков (ПС, БКРУ, КТП) последнюю ячейку не удаляем — там
    # держится структура. Контур — пустой контейнер, который пользователь собрал
    # сам: из него можно убрать единственную ячейку, иначе отмена добавления
    # ячейки упирается в 409.
    is_contour = (parent.attrs or {}).get("block_code") == "contour"
    if remaining <= 1 and not is_contour:
        raise conflict("Нельзя удалить последнюю ячейку блока", "block.last_cell")

    _delete_links_of(db, cell, actor)
    gis.soft_delete(db, cell, actor=actor)
    audit.add(
        "schema.cell_removed",
        entity="asset",
        entity_id=cell.id,
        detail=f"Из блока {parent.code} удалена ячейка {cell.code}",
    )


# --- перестановка оборудования между контейнерами (E-2) ---------------------


def is_container(asset: Asset) -> bool:
    """Блок схемы или контур: корневой объект, в который можно класть ячейки."""
    if asset.schema_block_id is not None:
        return False
    return asset.schema_role == "block" or bool((asset.attrs or {}).get("block_code"))


def _container_children(db: Session, container_id: uuid.UUID) -> list[Asset]:
    return list(
        db.scalars(
            select(Asset)
            .where(Asset.schema_block_id == container_id, Asset.deleted_at.is_(None))
            .order_by(Asset.schema_local_x.asc().nulls_last(), Asset.created_at.asc())
        )
    )


def _links_of_asset(db: Session, asset: Asset) -> list[Link]:
    port_ids = [port.id for port in asset.ports]
    if not port_ids:
        return []
    return list(
        db.scalars(
            select(Link).where(
                Link.deleted_at.is_(None),
                or_(Link.from_port_id.in_(port_ids), Link.to_port_id.in_(port_ids)),
            )
        )
    )


def _link_other_asset(db: Session, link: Link, asset: Asset) -> Asset | None:
    own_ports = {port.id for port in asset.ports}
    other_port_id = link.to_port_id if link.from_port_id in own_ports else link.from_port_id
    port = db.get(AssetPort, other_port_id)
    if port is None:
        return None
    return db.get(Asset, port.asset_id)


def _voltage_set(asset: Asset) -> set[float]:
    return {
        round(float(port.nominal_voltage_kv), 3)
        for port in asset.ports
        if port.nominal_voltage_kv is not None
    }


def _container_voltage(db: Session, container: Asset) -> float | None:
    values = _voltage_set(container)
    if not values:
        for child in _container_children(db, container.id):
            values |= _voltage_set(child)
    return values.pop() if len(values) == 1 else None


def _line_codes(db: Session, asset: Asset, *, with_children: bool = False) -> set[str]:
    targets = [asset] + (_container_children(db, asset.id) if with_children else [])
    codes: set[str] = set()
    for item in targets:
        for link in _links_of_asset(db, item):
            if link.line_id is None:
                continue
            line = db.get(Line, link.line_id)
            if line is not None:
                codes.add(line.code)
    return codes


def _would_cycle(db: Session, asset: Asset, target: Asset) -> bool:
    current: Asset | None = target
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        if current.id == asset.id:
            return True
        seen.add(current.id)
        current = db.get(Asset, current.parent_asset_id) if current.parent_asset_id else None
    return False


def _direction_issue(db: Session, asset: Asset, target: Asset | None) -> str | None:
    """Роль/направление элемента должно подходить шаблону целевого блока."""
    if target is None:
        return None
    block_code = (target.attrs or {}).get("block_code")
    if not block_code or block_code == "contour":
        return None
    block = db.scalar(select(SchemaBlock).where(SchemaBlock.code == block_code))
    if block is None:
        return None
    roles = {
        str(node.get("role"))
        for node in ((block.template_json or {}).get("nodes") or [])
        if node.get("role")
    }
    role = asset.schema_role or "cell"
    if not roles or role in ("cell", "block"):
        return None
    if role in ("input", "outgoing", "section") and role not in roles:
        return (
            f"Направление «{role}» не подходит для блока «{block.name}»: "
            f"допустимые роли — {', '.join(sorted(roles))}"
        )
    return None


def _move_reasons(
    db: Session, asset: Asset, target: Asset | None, source_block_id: uuid.UUID | None
) -> list[str]:
    """Почему перенос стоит подтвердить: перемычки, межконтейнерные связи, фидер."""
    reasons: list[str] = []
    siblings = (
        {child.id for child in _container_children(db, source_block_id)}
        if source_block_id is not None
        else set()
    )
    broken_jumpers = 0
    cross_links = 0
    for link in _links_of_asset(db, asset):
        other = _link_other_asset(db, link, asset)
        if other is None or other.id not in siblings:
            continue
        if link.link_type == "jumper":
            broken_jumpers += 1
        else:
            cross_links += 1
    if broken_jumpers:
        reasons.append(
            f"Перемычки с ячейками прежнего блока ({broken_jumpers}) перестанут "
            "отображаться в блоке после переноса"
        )
    if cross_links:
        reasons.append(
            f"Связи с объектами прежнего контейнера ({cross_links}) останутся "
            "между контейнерами — проверьте схему питания"
        )

    asset_lines = _line_codes(db, asset)
    target_lines = _line_codes(db, target, with_children=True) if target is not None else set()
    if asset_lines and target_lines and asset_lines.isdisjoint(target_lines):
        reasons.append(
            "Смена линии/фидера: объект на линии "
            f"{', '.join(sorted(asset_lines))}, контейнер — на линии "
            f"{', '.join(sorted(target_lines))}"
        )
    return reasons


def relocate(
    db: Session,
    asset: Asset,
    target: Asset | None,
    *,
    actor: Employee,
    confirm: bool = False,
    x: float | None = None,
    y: float | None = None,
    local_x: float | None = None,
    local_y: float | None = None,
) -> dict[str, Any]:
    """Атомарно перенести объект/ячейку в другой блок/контур (или на схему).

    Меняются только parent_asset_id/schema_block_id и локальные координаты —
    порты и связи не трогаем, поэтому существующие линии остаются валидными.
    При потенциальном разрыве перемычек/смене фидера требуется confirm=True.
    """
    if target is not None:
        if target.id == asset.id:
            raise ApiError(400, "schema.move.self", "Нельзя перенести объект в самого себя")
        if target.pit_id != asset.pit_id:
            raise not_found("Целевой контейнер не найден")
        if not is_container(target):
            raise ApiError(
                400,
                "schema.move.not_container",
                "Перенести можно только в блок или контур",
            )
        if _would_cycle(db, asset, target):
            raise ApiError(
                400,
                "schema.move.cycle",
                "Нельзя перенести контейнер внутрь себя или своего потомка",
            )

    if is_container(asset) or _container_children(db, asset.id):
        raise ApiError(
            400,
            "schema.move.container",
            "Контейнеры (блоки и контуры) не переносятся — переносите оборудование или ячейки",
        )

    source_block_id = asset.schema_block_id
    if target is None:
        if x is None or y is None:
            raise ApiError(
                400,
                "schema.move.position_required",
                "Укажите точку на схеме, куда вернуть объект без контейнера",
            )
        gis.check_bounds(db, asset.pit_id, x, y)

    if (asset.schema_role or "") in STRUCTURAL_ROLES and source_block_id != (
        target.id if target is not None else None
    ):
        raise conflict(
            "Структурный элемент блока (шина, ввод, ТТ, ОПН) переносить нельзя",
            "schema.move.structural_protected",
        )

    if target is not None:
        asset_voltage = _voltage_set(asset)
        target_voltage = _container_voltage(db, target)
        if len(asset_voltage) == 1 and target_voltage is not None:
            only_voltage = next(iter(asset_voltage))
            if abs(only_voltage - target_voltage) > 1e-6:
                raise conflict(
                    f"Напряжение объекта {only_voltage:g} кВ не совпадает с напряжением "
                    f"контейнера «{target.name}» {target_voltage:g} кВ — перенос невозможен",
                    "schema.move.voltage_mismatch",
                )
        direction_issue = _direction_issue(db, asset, target)
        if direction_issue:
            raise conflict(direction_issue, "schema.move.direction_conflict")

    reasons = _move_reasons(db, asset, target, source_block_id)
    if reasons and not confirm:
        raise ApiError(
            409,
            "schema.move.confirmation_required",
            "Перенос требует подтверждения:\n" + "\n".join(f"• {reason}" for reason in reasons),
            fields={
                "requires_confirm": "true",
                **{f"reason_{index + 1}": reason for index, reason in enumerate(reasons)},
            },
        )

    old = {
        "parent_id": asset.parent_asset_id,
        "block_id": asset.schema_block_id,
        "local_x": asset.schema_local_x,
        "local_y": asset.schema_local_y,
        "schema_x": asset.schema_x,
        "schema_y": asset.schema_y,
    }

    if target is None:
        asset.parent_asset_id = None
        asset.schema_block_id = None
        asset.schema_local_x = None
        asset.schema_local_y = None
        asset.schema_x = float(x) if x is not None else asset.schema_x
        asset.schema_y = float(y) if y is not None else asset.schema_y
    else:
        siblings = _container_children(db, target.id)
        if local_x is None:
            max_x = max([float(item.schema_local_x or 0) for item in siblings] or [0.0])
            local_x = max_x + 120
        if local_y is None:
            local_y = 220.0
        asset.parent_asset_id = target.id
        asset.schema_block_id = target.id
        asset.schema_local_x = float(local_x)
        asset.schema_local_y = float(local_y)

    asset.version = (asset.version or 1) + 1
    try:
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)

    audit.add(
        "schema.asset_relocated",
        entity="asset",
        entity_id=asset.id,
        detail=(
            f"Объект {asset.code} перенесён "
            + (f"в «{target.name}»" if target is not None else "на схему без контейнера")
        ),
        payload={
            "from_block_id": str(source_block_id) if source_block_id else None,
            "to_block_id": str(target.id) if target is not None else None,
            "confirm": confirm,
            "warnings": reasons,
        },
    )
    return {
        "asset": asset,
        "warnings": reasons,
        "old_parent_id": old["parent_id"],
        "old_block_id": old["block_id"],
        "old_local_x": old["local_x"],
        "old_local_y": old["local_y"],
        "old_schema_x": old["schema_x"],
        "old_schema_y": old["schema_y"],
    }


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

SYMBOL_TITLES = {
    "breaker": "Выключатель / ячейка",
    "disconnector": "Разъединитель",
    "busbar": "Секция шин",
    "load": "Электроприёмник",
    "generator": "Генератор",
    "source": "Питание / ПС",
    "line": "Опора ВЛ",
    "ct": "Трансформатор тока",
    "arrester": "ОПН",
}


def set_collapsed(db: Session, parent: Asset, collapsed: bool, actor: Employee) -> bool:
    if parent.schema_role != "block":
        raise ApiError(400, "block.not_block", "Объект не является блоком схемы")
    parent.attrs = {**(parent.attrs or {}), "collapsed": bool(collapsed)}
    db.commit()
    audit.add(
        "schema.block_collapsed" if collapsed else "schema.block_expanded",
        entity="asset",
        entity_id=parent.id,
        detail=f"Блок {parent.code} {'свёрнут' if collapsed else 'развёрнут'}",
    )
    return bool(collapsed)


def create_jumper(
    db: Session,
    parent: Asset,
    from_cell_id: uuid.UUID,
    to_cell_id: uuid.UUID,
    actor: Employee,
    *,
    label: str | None = None,
) -> dict:
    if parent.schema_role != "block":
        raise ApiError(400, "block.not_block", "Объект не является блоком схемы")
    source = db.get(Asset, from_cell_id)
    target = db.get(Asset, to_cell_id)
    for asset in (source, target):
        if asset is None or asset.deleted_at is not None:
            raise not_found("Ячейка не найдена")
        if asset.schema_block_id != parent.id:
            raise conflict(
                "Перемычка возможна только между ячейками одного блока",
                "block.jumper_foreign",
            )
    if source.id == target.id:
        raise conflict("Нельзя соединить ячейку саму с собой", "block.jumper_self")

    link = links_service.create_link(
        db,
        parent.pit_id,
        __import__("app.schemas.gis", fromlist=["LinkCreate"]).LinkCreate(
            from_port_id=_port(source, "out"),
            to_port_id=_port(target, "in"),
            link_type="jumper",
            cable_mark=label,
        ),
        actor=actor,
    )
    audit.add(
        "schema.jumper_created",
        entity="asset",
        entity_id=parent.id,
        detail=f"Перемычка {source.name} → {target.name}",
    )
    return {"id": str(link.id), "from": source.code, "to": target.code}


def legend(db: Session) -> list[dict]:
    rows = db.execute(
        select(AssetType.schema_symbol, func.count(Asset.id))
        .join(Asset, Asset.asset_type_id == AssetType.id)
        .where(Asset.deleted_at.is_(None))
        .group_by(AssetType.schema_symbol)
    ).all()
    seen: dict[str, int] = {}
    for symbol, count in rows:
        seen[symbol] = seen.get(symbol, 0) + int(count)
    return [
        {"symbol": symbol, "title": SYMBOL_TITLES.get(symbol, symbol), "count": count}
        for symbol, count in sorted(seen.items(), key=lambda item: -item[1])
    ]


# --- построение линии: пакетные ячейки, кабели, оборудование -----------------

def _ensure_in_out(db: Session, asset: Asset) -> None:
    """Гарантировать вход и выход: без портов кабель некуда подключить."""
    created = 0
    for code, name, kind in (("IN-1", "Ввод", "in"), ("OUT-1", "Выход", "out")):
        if not any(port.code == code for port in asset.ports):
            db.add(
                AssetPort(id=uuid.uuid4(), asset_id=asset.id, code=code, name=name, kind=kind, sort_order=10)
            )
            created += 1
    if created:
        db.commit()
        db.refresh(asset)


def _pick_port(asset: Asset, want: tuple[str, ...], explicit: uuid.UUID | None) -> AssetPort:
    ports = list(asset.ports)
    if explicit is not None:
        for port in ports:
            if port.id == explicit:
                return port
        raise ApiError(400, "link.port_foreign", "Порт не принадлежит выбранному объекту")
    preferred = [port for port in ports if port.kind in want]
    if preferred:
        return preferred[0]
    return ports[0]


def add_cells_bulk(
    db: Session,
    parent: Asset,
    actor: Employee,
    *,
    count: int,
    start: int,
    prefix: str,
    suffix: str,
    section_size: int,
    section_prefix: str,
    role: str = "outgoing",
    type_code: str | None = None,
) -> list[Asset]:
    """Создать пачку ячеек с сквозной нумерацией и метками секций."""
    if parent.schema_role not in ("block", None):
        raise ApiError(400, "block.not_block", "Объект не является блоком схемы")
    if role in STRUCTURAL_ROLES:
        raise ApiError(400, "block.structural_role", "Нельзя добавить структурный элемент вручную")

    siblings = db.scalars(
        select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
    ).all()
    base_x = max([float(item.schema_local_x or 0) for item in siblings] or [0])

    created: list[Asset] = []
    for index in range(count):
        number = start + index
        label = f"{prefix}{number}{suffix}"
        params: dict[str, Any] = {"sequence_no": number}
        if section_size > 0:
            section_no = index // section_size + 1
            params["section_no"] = section_no
            params["section"] = f"{section_prefix} {section_no}"
        node = {
            "key": f"cell{uuid.uuid4().hex[:4]}",
            "role": role,
            "label": label,
            "type_code": type_code or "cell",
            "x": base_x + 120 + index * 110,
            "y": 220,
            "params": params,
        }
        child = _create_child(
            db,
            parent=parent,
            node=node,
            actor=actor,
            code_suffix=f"{parent.code}-{node['key']}"[:64],
        )
        created.append(child)

    audit.add(
        "schema.cells_bulk_added",
        entity="asset",
        entity_id=parent.id,
        detail=f"В блок {parent.code} добавлено ячеек: {count} (с №{start})"
        + (f", секций по {section_size}" if section_size > 0 else ""),
    )
    return created


def create_cable(
    db: Session,
    from_asset: Asset,
    to_asset: Asset,
    actor: Employee,
    *,
    from_port_id: uuid.UUID | None = None,
    to_port_id: uuid.UUID | None = None,
    cable_mark: str | None = None,
    length_m: float | None = None,
    cross_section_mm2: float | None = None,
    cores: int | None = None,
    link_type: str = "cable",
):
    """Кабельная/воздушная связь между двумя объектами с подбором портов."""
    if from_asset.id == to_asset.id:
        raise conflict("Нельзя соединить объект сам с собой", "link.same_asset")

    _ensure_in_out(db, from_asset)
    _ensure_in_out(db, to_asset)

    from_port = _pick_port(from_asset, ("out", "io"), from_port_id)
    to_port = _pick_port(to_asset, ("in", "io"), to_port_id)

    payload = LinkCreate(
        from_port_id=from_port.id,
        to_port_id=to_port.id,
        link_type=link_type,
        cable_mark=cable_mark,
        length_m=length_m,
        cross_section_mm2=cross_section_mm2,
        cores=cores,
    )
    link = links_service.create_link(db, from_asset.pit_id, payload, actor=actor)
    audit.add(
        "schema.cable_created",
        entity="link",
        entity_id=uuid.UUID(str(link.id)),
        detail=f"Кабель {from_asset.code} → {to_asset.code}"
        + (f" ({cable_mark})" if cable_mark else ""),
    )
    return link


def add_line_equipment(
    db: Session,
    anchor: Asset,
    actor: Employee,
    *,
    type_code: str,
    name: str | None,
    cable_mark: str | None = None,
    link_type: str = "cable",
) -> dict[str, Any]:
    """Добавить КТП/ЯКУ/разъединитель в линию: объект реестра + связь с опорой."""
    asset_type = gis.get_type(db, type_code)
    asset = gis.create_asset(
        db,
        AssetCreate(
            name=(name or asset_type.name).strip(),
            type_code=asset_type.code,
            status="off",
        ),
        actor=actor,
    )

    if anchor.schema_x is not None:
        asset.schema_x = float(anchor.schema_x) + 150
        asset.schema_y = float(anchor.schema_y) + (60 if anchor.schema_y is not None else 0)
        db.commit()
        db.refresh(asset)

    link = create_cable(
        db,
        anchor,
        asset,
        actor,
        cable_mark=cable_mark,
        link_type=link_type,
    )
    audit.add(
        "schema.line_equipment_added",
        entity="asset",
        entity_id=asset.id,
        detail=f"В линию к {anchor.code} добавлено оборудование {asset.code} ({asset_type.name})",
    )
    return {"asset": asset, "link": link}