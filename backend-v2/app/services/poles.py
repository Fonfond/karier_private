"""Генерация и нумерация опор ВЛ на схеме."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict
from app.models import Asset, AssetPort, AssetType, Employee, Link
from app.schemas.gis import AssetCreate, LinkCreate
from app.services import audit, gis
from app.services import links as links_service


def _pole_type(db: Session, code: str | None) -> AssetType:
    candidates = [code] if code else ["pole", "op", "yacheyka"]
    for candidate in candidates:
        if not candidate:
            continue
        asset_type = db.scalar(select(AssetType).where(AssetType.code == candidate))
        if asset_type is not None:
            return asset_type
    raise ApiError(400, "pole.type_not_found", "Нет типа «Опора» (pole/op)")


def _ensure_ports(db: Session, asset: Asset) -> None:
    existing = {port.code for port in asset.ports}
    for code, name, kind in (("IN-1", "Ввод", "in"), ("OUT-1", "Выход", "out")):
        if code not in existing:
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
    db.flush()
    db.refresh(asset)


def _port(asset: Asset, kind: str) -> AssetPort | None:
    return next((p for p in asset.ports if p.kind == kind or p.kind == "io"), None)


def generate(
    db: Session,
    actor: Employee,
    *,
    type_code: str | None,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    count: int,
    start: int,
    step: int,
    prefix: str,
    source_asset_id: uuid.UUID | None = None,
    target_asset_id: uuid.UUID | None = None,
    link_type: str = "overhead",
    path: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    if count < 1 or count > 200:
        raise ApiError(400, "pole.count", "Количество опор — от 1 до 200")
    if step < 1:
        raise ApiError(400, "pole.step", "Шаг нумерации должен быть ≥ 1")

    asset_type = _pole_type(db, type_code)
    pit = gis.get_pit(db)
    source = db.get(Asset, source_asset_id) if source_asset_id is not None else None
    target = db.get(Asset, target_asset_id) if target_asset_id is not None else None
    if source is not None and (source.x is None or source.y is None):
        raise ApiError(400, "pole.source_no_coords", "У объекта-источника нет координат на карте")
    if target is not None and (target.x is None or target.y is None):
        raise ApiError(400, "pole.target_no_coords", "У объекта-приёмника нет координат на карте")

    points = list(path or [(x1, y1), (x2, y2)])
    if source is not None:
        points = [(float(source.x), float(source.y))] + [pt for pt in points if pt != (float(source.x), float(source.y))]
    if target is not None:
        points = points + [(float(target.x), float(target.y))]
    if len(points) < 2:
        raise ApiError(400, "pole.path", "Нужно минимум две точки линии")
    for px, py in points:
        gis.check_bounds(db, pit.id, px, py)

    # равномерное распределение по длине ломаной
    lengths = [
        ((points[i + 1][0] - points[i][0]) ** 2 + (points[i + 1][1] - points[i][1]) ** 2) ** 0.5
        for i in range(len(points) - 1)
    ]
    total = sum(lengths) or 1.0

    def point_at(distance: float) -> tuple[float, float]:
        remaining = distance
        for index, segment in enumerate(lengths):
            if remaining <= segment or index == len(lengths) - 1:
                ratio = min(remaining / segment, 1.0) if segment else 0.0
                ax, ay = points[index]
                bx, by = points[index + 1]
                return (ax + (bx - ax) * ratio, ay + (by - ay) * ratio)
            remaining -= segment
        return points[-1]

    anchored = source is not None or target is not None
    poles: list[Asset] = []
    for index in range(count):
        if anchored:
            # опоры внутри пролёта «оборудование → оборудование», без крайних точек
            ratio = (index + 1) / (count + 1)
        else:
            ratio = index / (count - 1) if count > 1 else 0.0
        x, y = point_at(total * ratio)
        x = round(x, 1)
        y = round(y, 1)
        number = start + index * step
        label = f"{prefix}{number}"
        asset = gis.create_asset(
            db,
            AssetCreate(name=label, type_code=asset_type.code, x=x, y=y, status="on"),
            actor=actor,
        )
        asset.attrs = {**(asset.attrs or {}), "pole_no": label}
        asset.schema_role = "line"
        _ensure_ports(db, asset)
        poles.append(asset)

    db.commit()

    for previous, current in zip(poles, poles[1:]):
        from_port = _port(previous, "out")
        to_port = _port(current, "in")
        if from_port and to_port:
            links_service.create_link(
                db,
                pit.id,
                LinkCreate(
                    from_port_id=from_port.id,
                    to_port_id=to_port.id,
                    link_type=link_type,
                    cable_mark="ВЛ 6 кВ",
                    length_m=max(1.0, round(total / max(count - 1, 1), 1)),
                ),
                actor=actor,
            )

    if source_asset_id is not None:
        if source is None:
            raise ApiError(404, "asset.not_found", "Объект-источник не найден")
        _ensure_ports(db, source)
        from_port = _port(source, "out")
        to_port = _port(poles[0], "in")
        if from_port and to_port:
            links_service.create_link(
                db,
                pit.id,
                LinkCreate(
                    from_port_id=from_port.id,
                    to_port_id=to_port.id,
                    link_type=link_type,
                    cable_mark="ВЛ 6 кВ",
                ),
                actor=actor,
            )

    if target is not None and poles:
        _ensure_ports(db, target)
        from_port = _port(poles[-1], "out")
        to_port = _port(target, "in")
        if from_port and to_port:
            links_service.create_link(
                db,
                pit.id,
                LinkCreate(
                    from_port_id=from_port.id,
                    to_port_id=to_port.id,
                    link_type=link_type,
                    cable_mark="ВЛ 6 кВ",
                ),
                actor=actor,
            )

    audit.add(
        "schema.poles_generated",
        entity="asset",
        entity_id=poles[0].id,
        detail=f"Создано опор: {count} ({prefix}{start}…{prefix}{start + (count - 1) * step})",
        payload={"ids": [str(pole.id) for pole in poles]},
    )
    return {
        "count": len(poles),
        "ids": [str(pole.id) for pole in poles],
        "first": poles[0].name,
        "last": poles[-1].name,
    }


def renumber(
    db: Session,
    actor: Employee,
    *,
    type_code: str | None,
    start: int,
    step: int,
    prefix: str,
) -> dict[str, Any]:
    asset_type = _pole_type(db, type_code)
    if step < 1:
        raise ApiError(400, "pole.step", "Шаг нумерации должен быть ≥ 1")

    poles = list(
        db.scalars(
            select(Asset)
            .where(
                Asset.asset_type_id == asset_type.id,
                Asset.deleted_at.is_(None),
            )
            .order_by(Asset.schema_x.nulls_last(), Asset.schema_y.nulls_last(), Asset.code)
        ).all()
    )
    if not poles:
        raise conflict("Опор этого типа нет", "pole.empty")

    for index, pole in enumerate(poles):
        label = f"{prefix}{start + index * step}"
        pole.name = label
        pole.attrs = {**(pole.attrs or {}), "pole_no": label}
    db.commit()
    audit.add(
        "schema.poles_renumbered",
        detail=f"Перенумеровано опор: {len(poles)}",
        payload={"count": len(poles), "start": start, "step": step},
    )
    return {"count": len(poles), "first": poles[0].name, "last": poles[-1].name}

def _pole_links(db: Session, asset_type_id: uuid.UUID) -> list[tuple[Asset, Asset]]:
    """Пары соседних опор, соединённых связями ВЛ."""
    links = db.scalars(
        select(Link).where(Link.deleted_at.is_(None), Link.link_type == "overhead")
    ).all()
    pairs: list[tuple[Asset, Asset]] = []
    for link in links:
        from_port, to_port = link.from_port, link.to_port
        if from_port is None or to_port is None:
            continue
        a, b = from_port.asset, to_port.asset
        if a is None or b is None:
            continue
        if a.asset_type_id == asset_type_id and b.asset_type_id == asset_type_id:
            pairs.append((a, b))
    return pairs


def renumber_chain(
    db: Session,
    actor: Employee,
    *,
    anchor_asset_id: uuid.UUID | None,
    link_id: uuid.UUID | None,
    start: int,
    step: int,
    prefix: str,
    type_code: str | None = None,
) -> dict[str, Any]:
    if step < 1:
        raise ApiError(400, "pole.step", "Шаг нумерации должен быть ≥ 1")

    asset_type = _pole_type(db, type_code)
    anchor: Asset | None = None
    if anchor_asset_id is not None:
        anchor = db.get(Asset, anchor_asset_id)
    elif link_id is not None:
        link = db.get(Link, link_id)
        if link is None or link.from_port is None:
            raise ApiError(404, "link.not_found", "Связь не найдена")
        anchor = link.from_port.asset if link.from_port.asset.asset_type_id == asset_type.id else link.to_port.asset
    if anchor is None or anchor.asset_type_id != asset_type.id:
        raise ApiError(400, "pole.anchor", "Выберите опору этой линии")

    pairs = _pole_links(db, asset_type.id)
    neighbours: dict[uuid.UUID, list[Asset]] = {}
    by_id = {anchor.id: anchor}
    for a, b in pairs:
        neighbours.setdefault(a.id, []).append(b)
        neighbours.setdefault(b.id, []).append(a)
        by_id[a.id] = a
        by_id[b.id] = b

    if anchor.id not in neighbours:
        chain = [anchor]
    else:
        # идём к концу цепочки, затем проходим её целиком
        start_node = anchor
        previous: uuid.UUID | None = None
        while True:
            options = [n for n in neighbours.get(start_node.id, []) if n.id != previous]
            if not options:
                break
            previous = start_node.id
            start_node = options[0]

        chain = []
        previous = None
        current = start_node
        visited: set[uuid.UUID] = set()
        while current is not None and current.id not in visited:
            chain.append(current)
            visited.add(current.id)
            options = [n for n in neighbours.get(current.id, []) if n.id != previous and n.id not in visited]
            previous = current.id
            current = options[0] if options else None

    for index, pole in enumerate(chain):
        label = f"{prefix}{start + index * step}"
        pole.name = label
        pole.attrs = {**(pole.attrs or {}), "pole_no": label}
    db.commit()
    audit.add(
        "schema.poles_renumbered_chain",
        detail=f"Перенумерована линия из {len(chain)} опор",
        payload={"count": len(chain), "start": start, "step": step},
    )
    return {"count": len(chain), "first": chain[0].name, "last": chain[-1].name}
