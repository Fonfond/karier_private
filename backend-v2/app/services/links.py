"""Связи и линии: создание, правка, удаление, сериализация."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict, not_found
from app.models import Asset, AssetPort, Line, Link
from app.schemas.gis import (
    AssetRefOut,
    LineCreate,
    LineOut,
    LinkCreate,
    LinkOut,
    LinkUpdate,
    PortRefOut,
)
from app.services import audit, topology


def _asset_ref(port: AssetPort) -> AssetRefOut:
    asset = port.asset
    return AssetRefOut(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        type_code=asset.asset_type.code if asset.asset_type else "",
        type_icon=asset.asset_type.icon if asset.asset_type else None,
        status=asset.status,
    )


def _port_ref(port: AssetPort) -> PortRefOut:
    return PortRefOut(
        id=port.id,
        code=port.code,
        name=port.name,
        kind=port.kind,
        voltage_kv=float(port.nominal_voltage_kv) if port.nominal_voltage_kv else None,
        schema_x=float(port.schema_x) if port.schema_x is not None else None,
        schema_y=float(port.schema_y) if port.schema_y is not None else None,
    )


def link_label(link: Link) -> str:
    if link.line is not None:
        return link.line.code
    if link.cable_mark:
        return link.cable_mark
    return f"{link.from_port.code}→{link.to_port.code}"


def line_out(line: Line, links_count: int = 0) -> LineOut:
    return LineOut(
        id=line.id,
        code=line.code,
        name=line.name,
        kind=line.kind,
        voltage_kv=float(line.voltage_kv) if line.voltage_kv else None,
        conductor_mark=line.conductor_mark,
        length_m=float(line.length_m) if line.length_m else None,
        state=line.state,
        links_count=links_count,
    )


def link_out(link: Link, warnings: list[str] | None = None) -> LinkOut:
    return LinkOut(
        id=link.id,
        from_asset=_asset_ref(link.from_port),
        to_asset=_asset_ref(link.to_port),
        from_port=_port_ref(link.from_port),
        to_port=_port_ref(link.to_port),
        link_type=link.link_type,
        feed_role=link.feed_role,
        state=link.state,
        cable_mark=link.cable_mark,
        cable_no=link.cable_no,
        cable_status=link.cable_status,
        installed_on=link.installed_on,
        route_note=link.route_note,
        length_m=float(link.length_m) if link.length_m else None,
        cross_section_mm2=float(link.cross_section_mm2) if link.cross_section_mm2 else None,
        cores=link.cores,
        line=line_out(link.line) if link.line else None,
        label=link_label(link),
        version=link.version,
        warnings=warnings or [],
    )


# --- чтение ---------------------------------------------------------------

def list_links(
    db: Session,
    pit_id: uuid.UUID,
    *,
    asset_id: uuid.UUID | None = None,
    state: str | None = None,
    link_type: str | None = None,
) -> list[Link]:
    stmt = select(Link).where(Link.pit_id == pit_id, Link.deleted_at.is_(None))
    if state:
        stmt = stmt.where(Link.state == state)
    if link_type:
        stmt = stmt.where(Link.link_type == link_type)
    if asset_id is not None:
        from sqlalchemy import or_

        port_ids = select(AssetPort.id).where(AssetPort.asset_id == asset_id)
        stmt = stmt.where(
            or_(Link.from_port_id.in_(port_ids), Link.to_port_id.in_(port_ids))
        )
    return list(db.scalars(stmt.order_by(Link.created_at)).unique().all())


def get_link(db: Session, link_id: uuid.UUID) -> Link:
    link = db.get(Link, link_id)
    if link is None or link.deleted_at is not None:
        raise not_found("Связь не найдена")
    return link


def get_link_any(db: Session, link_id: uuid.UUID) -> Link:
    """Связь без фильтра архива — нужна для отмены удаления."""
    link = db.get(Link, link_id)
    if link is None:
        raise not_found("Связь не найдена")
    return link


def _get_port(db: Session, port_id: uuid.UUID) -> AssetPort:
    port = db.get(AssetPort, port_id)
    if port is None:
        raise not_found(f"Порт {port_id} не найден")
    return port


# --- изменение ------------------------------------------------------------

def create_link(db: Session, pit_id: uuid.UUID, payload: LinkCreate, *, actor) -> LinkOut:
    from_port = _get_port(db, payload.from_port_id)
    to_port = _get_port(db, payload.to_port_id)

    if from_port.asset.pit_id != pit_id or to_port.asset.pit_id != pit_id:
        raise ApiError(400, "link.other_pit", "Порты принадлежат другому карьеру")

    warnings = topology.validate_new_link(
        db,
        from_port=from_port,
        to_port=to_port,
        link_type=payload.link_type,
        feed_role=payload.feed_role,
    )

    if payload.line_id is not None:
        line = db.get(Line, payload.line_id)
        if line is None or line.pit_id != pit_id:
            raise ApiError(400, "line.not_found", "Линия не найдена")

    link = Link(
        id=uuid.uuid4(),
        pit_id=pit_id,
        from_port_id=payload.from_port_id,
        to_port_id=payload.to_port_id,
        line_id=payload.line_id,
        link_type=payload.link_type,
        feed_role=payload.feed_role,
        state=payload.state,
        cable_mark=payload.cable_mark,
        cable_no=payload.cable_no,
        cable_status=payload.cable_status,
        installed_on=payload.installed_on,
        route_note=payload.route_note,
        length_m=payload.length_m,
        cross_section_mm2=payload.cross_section_mm2,
        cores=payload.cores,
        geometry=payload.geometry or [],
        attrs=payload.attrs or {},
        created_by=actor.id,
        updated_by=actor.id,
        version=1,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    audit.add(
        "link.created",
        entity="link",
        entity_id=link.id,
        detail=(
            f"Связь {from_port.asset.code}:{from_port.code} → "
            f"{to_port.asset.code}:{to_port.code} ({payload.link_type}, {payload.feed_role})"
        ),
        payload={"from_port_id": str(from_port.id), "to_port_id": str(to_port.id)},
    )
    return link_out(link, warnings)


def update_link(db: Session, link: Link, payload: LinkUpdate, *, actor) -> LinkOut:
    if payload.expected_version is not None and payload.expected_version != link.version:
        raise conflict(
            f"Связь изменена другим пользователем (версия {link.version})", "conflict.version"
        )

    data = payload.model_dump(exclude_unset=True)
    data.pop("expected_version", None)

    if "state" in data and data["state"] is not None:
        audit.add(
            "link.state_changed",
            entity="link",
            entity_id=link.id,
            detail=f"Связь {link_label(link)}: {link.state} → {data['state']}",
        )
    if "line_id" in data and data["line_id"] is not None:
        line = db.get(Line, data["line_id"])
        if line is None or line.pit_id != link.pit_id:
            raise ApiError(400, "line.not_found", "Линия не найдена")

    for field, value in data.items():
        setattr(link, field, value)
    link.updated_by = actor.id
    link.version = (link.version or 1) + 1
    db.commit()
    db.refresh(link)

    audit.add(
        "link.updated",
        entity="link",
        entity_id=link.id,
        detail=f"Изменена связь {link_label(link)}",
    )
    return link_out(link)


def delete_link(db: Session, link: Link, *, actor) -> None:
    label = link_label(link)
    link.deleted_at = func.now()
    link.deleted_by = actor.id
    link.version = (link.version or 1) + 1
    db.commit()
    audit.add("link.deleted", entity="link", entity_id=link.id, detail=f"Удалена связь {label}")


def restore_link(db: Session, link: Link, *, actor) -> LinkOut:
    """Вернуть связь из архива (отмена удаления).

    Восстановление возможно, только если оба объекта живы и пара портов снова
    свободна — иначе связь вернулась бы «в никуда» или создала дубль.
    """
    if link.deleted_at is None:
        raise conflict("Связь не в архиве", "link.not_archived")

    from_port = db.get(AssetPort, link.from_port_id)
    to_port = db.get(AssetPort, link.to_port_id)
    if from_port is None or to_port is None:
        raise conflict("Порты связи не найдены", "link.ports_missing")

    for port in (from_port, to_port):
        asset = db.get(Asset, port.asset_id)
        if asset is None or asset.deleted_at is not None:
            raise conflict("Объект связи находится в архиве", "link.asset_archived")

    duplicate = db.scalar(
        select(Link).where(
            Link.from_port_id == link.from_port_id,
            Link.to_port_id == link.to_port_id,
            Link.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise conflict("Такая связь уже существует", "link.duplicate")

    link.deleted_at = None
    link.deleted_by = None
    link.version = (link.version or 1) + 1
    db.commit()
    audit.add(
        "link.restored",
        entity="link",
        entity_id=link.id,
        detail=f"Восстановлена связь {link_label(link)}",
    )
    return link_out(link)


# --- линии ----------------------------------------------------------------

def create_line(db: Session, pit_id: uuid.UUID, payload: LineCreate, *, actor) -> LineOut:
    duplicate = db.scalar(
        select(Line).where(Line.pit_id == pit_id, Line.code == payload.code, Line.deleted_at.is_(None))
    )
    if duplicate is not None:
        raise conflict(f"Линия {payload.code} уже существует", "line.duplicate_code")

    line = Line(
        id=uuid.uuid4(),
        pit_id=pit_id,
        code=payload.code,
        name=payload.name,
        kind=payload.kind,
        voltage_kv=payload.voltage_kv,
        conductor_mark=payload.conductor_mark,
        length_m=payload.length_m,
        state="deenergized",
        status="in_service",
    )
    db.add(line)
    db.commit()
    audit.add("line.created", entity="line", entity_id=line.id, detail=f"Создана линия {line.code}")
    return line_out(line)


def list_lines(db: Session, pit_id: uuid.UUID) -> list[LineOut]:
    rows = db.execute(
        select(Line, func.count(Link.id))
        .outerjoin(Link, (Link.line_id == Line.id) & (Link.deleted_at.is_(None)))
        .where(Line.pit_id == pit_id, Line.deleted_at.is_(None))
        .group_by(Line.id)
        .order_by(Line.code)
    ).all()
    return [line_out(line, int(count)) for line, count in rows]
