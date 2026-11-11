"""Генерация и нумерация опор ВЛ на схеме."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict
from app.models import Asset, AssetPort, AssetType, Employee
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
    link_type: str = "overhead",
) -> dict[str, Any]:
    if count < 1 or count > 200:
        raise ApiError(400, "pole.count", "Количество опор — от 1 до 200")
    if step < 1:
        raise ApiError(400, "pole.step", "Шаг нумерации должен быть ≥ 1")

    asset_type = _pole_type(db, type_code)
    pit = gis.get_pit(db)
    gis.check_bounds(db, pit.id, x1, y1)
    gis.check_bounds(db, pit.id, x2, y2)

    poles: list[Asset] = []
    for index in range(count):
        ratio = index / (count - 1) if count > 1 else 0.0
        x = round(x1 + (x2 - x1) * ratio, 1)
        y = round(y1 + (y2 - y1) * ratio, 1)
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
                    length_m=max(1.0, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 / max(count - 1, 1), 1)),
                ),
                actor=actor,
            )

    if source_asset_id is not None:
        source = db.get(Asset, source_asset_id)
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
