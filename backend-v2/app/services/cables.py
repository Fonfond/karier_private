"""Кабельный учёт этапа 2: кабель как объект реестра и установка на линию.

Кабель — обычный объект ``gis.assets`` класса ``cable`` с колонкой
``lifecycle_status`` (``installed`` / ``reserve`` / ``repair``, миграция 0015).
Связь ``gis.links.cable_asset_id`` (миграция 0016) указывает, на каком участке
кабель установлен; поля ``cable_mark``/``length_m``/``cross_section_mm2`` связи
остаются денормализацией для старых отчётов и заполняются из карточки кабеля.

Маршруты (``app/api/routers/cables.py``):

* ``GET  /api/cables?lifecycle_status=`` — список с фильтром по состоянию;
* ``POST /api/cables/{cable_id}/install`` — на линию (``link_id``) или на объект
  (``asset_id``, связь создаётся/подбирается);
* ``POST /api/cables/{cable_id}/return`` — снять кабель: состояние ``reserve``
  (по умолчанию) или ``repair``, ссылки ``cable_asset_id`` очищаются.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError, conflict
from app.models import Asset, AssetPort, AssetType, Employee, Link
from app.services import asset_fields, audit, gis
from app.services import links as links_service

LIFECYCLE_STATUSES = ("installed", "reserve", "repair")
CABLE_LINK_TYPES = ("cable", "overhead")

#: Что снимается со связи вместе с кабелем (F4). Марка/длина/сечение — это
#: денормализация карточки кабеля; после снятия они не должны «висеть» на линии,
#: иначе схема/отчёты показывают параметры уже снятого кабеля.
DETACHED_LINK_FIELDS = ("cable_asset_id", "cable_mark", "length_m", "cross_section_mm2")


# --- распознавание кабеля ---------------------------------------------------


def is_cable(asset: Asset) -> bool:
    return asset_fields.effective_class(asset.asset_type) == "cable"


def _require_cable(asset: Asset) -> None:
    if is_cable(asset):
        return
    raise ApiError(
        422,
        "cable.not_cable",
        "Объект не является кабелем: ожидается тип класса «Кабель»",
    )


def _cable_type_ids():
    return select(AssetType.id).where(
        or_(AssetType.equipment_class == "cable", AssetType.code == "cable")
    )


def effective_status(asset: Asset) -> str:
    status = (asset.lifecycle_status or "").strip().lower()
    return status if status in LIFECYCLE_STATUSES else "installed"


# --- сериализация -----------------------------------------------------------


def _asset_ref(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "code": asset.code,
        "name": asset.name,
        "type_code": asset.asset_type.code if asset.asset_type else "",
        "type_icon": asset.asset_type.icon if asset.asset_type else None,
        "status": asset.status,
    }


def _attr_float(asset: Asset, key: str) -> float | None:
    raw = (asset.attrs or {}).get(key)
    if raw is None or raw == "":
        return None
    try:
        return round(float(raw), 3)
    except (TypeError, ValueError):
        return None


def cable_out(cable: Asset, link: Link | None = None, conflicting: list[Link] | None = None) -> dict[str, Any]:
    attrs = cable.attrs or {}
    link_mark = link.cable_mark if link is not None else None
    length = link.length_m if link is not None and link.length_m is not None else _attr_float(cable, "length_m")
    section = (
        link.cross_section_mm2
        if link is not None and link.cross_section_mm2 is not None
        else _attr_float(cable, "section_mm2")
    )
    return {
        "id": cable.id,
        "code": cable.code,
        "name": cable.name,
        "type_code": cable.asset_type.code if cable.asset_type else "",
        "status": cable.status,
        "lifecycle_status": effective_status(cable),
        "cable_mark": attrs.get("cable_mark") or link_mark,
        "section_mm2": section,
        "length_m": length,
        "voltage_kv": _attr_float(cable, "voltage_kv"),
        "link_id": link.id if link is not None else None,
        "link_label": links_service.link_label(link) if link is not None else None,
        "link_state": link.state if link is not None else None,
        "installed_on": (cable.attrs or {}).get("installed_on"),
        "from_asset": _asset_ref(link.from_port.asset) if link is not None else None,
        "to_asset": _asset_ref(link.to_port.asset) if link is not None else None,
        "attrs": dict(attrs),
        "version": cable.version,
        "updated_at": cable.updated_at,
        "warnings": [
            f"Кабель установлен на нескольких связях: {', '.join(str(item.id) for item in conflicting)}"
        ]
        if conflicting
        else [],
    }


def _links_by_cable(db: Session, cable_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Link]]:
    if not cable_ids:
        return {}
    rows = db.scalars(
        select(Link)
        .where(Link.cable_asset_id.in_(cable_ids), Link.deleted_at.is_(None))
        .order_by(Link.created_at)
    ).unique().all()
    grouped: dict[uuid.UUID, list[Link]] = {}
    for link in rows:
        grouped.setdefault(link.cable_asset_id, []).append(link)
    return grouped


# --- чтение -----------------------------------------------------------------


def list_cables(
    db: Session,
    *,
    lifecycle_status: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    pit = gis.get_pit(db)
    status = (lifecycle_status or "").strip().lower() or None
    if status is not None and status not in LIFECYCLE_STATUSES:
        raise ApiError(
            422,
            "validation.failed",
            "Недопустимое состояние кабеля",
            fields={"lifecycle_status": "Допустимо installed, reserve, repair"},
        )

    stmt = (
        select(Asset)
        .where(
            Asset.pit_id == pit.id,
            Asset.deleted_at.is_(None),
            Asset.asset_type_id.in_(_cable_type_ids()),
        )
        .options(selectinload(Asset.ports))
        .order_by(Asset.code)
        .limit(max(1, min(int(limit), 1000)))
    )
    if status == "installed":
        # Кабели, созданные до этапа 1, могли остаться без колонки: для них
        # состояние по умолчанию — «установлен» (как и в create_asset).
        stmt = stmt.where(
            or_(Asset.lifecycle_status == "installed", Asset.lifecycle_status.is_(None))
        )
    elif status is not None:
        stmt = stmt.where(Asset.lifecycle_status == status)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Asset.code.ilike(needle), Asset.name.ilike(needle)))

    cables = list(db.scalars(stmt).unique().all())
    grouped = _links_by_cable(db, [cable.id for cable in cables])
    result = []
    for cable in cables:
        links = grouped.get(cable.id, [])
        primary = links[0] if links else None
        result.append(cable_out(cable, primary, links[1:] if len(links) > 1 else None))
    return result


def get_cable(db: Session, cable_id: uuid.UUID) -> Asset:
    cable = gis.get_asset(db, cable_id)
    _require_cable(cable)
    return cable


# --- установка и снятие -----------------------------------------------------


def _active_links_of(db: Session, asset_id: uuid.UUID) -> list[Link]:
    port_ids = select(AssetPort.id).where(AssetPort.asset_id == asset_id)
    return list(
        db.scalars(
            select(Link)
            .where(
                Link.deleted_at.is_(None),
                or_(Link.from_port_id.in_(port_ids), Link.to_port_id.in_(port_ids)),
            )
            .order_by(Link.created_at)
        )
        .unique()
        .all()
    )


def _link_between(db: Session, first_id: uuid.UUID, second_id: uuid.UUID) -> Link | None:
    first_ports = select(AssetPort.id).where(AssetPort.asset_id == first_id)
    second_ports = select(AssetPort.id).where(AssetPort.asset_id == second_id)
    return db.scalar(
        select(Link).where(
            Link.deleted_at.is_(None),
            or_(
                (Link.from_port_id.in_(first_ports)) & (Link.to_port_id.in_(second_ports)),
                (Link.from_port_id.in_(second_ports)) & (Link.to_port_id.in_(first_ports)),
            ),
        )
    )


def _detach(db: Session, cable: Asset, link: Link, actor: Employee) -> dict[str, Any]:
    """Снять кабель со связи и очистить денормализацию (F4).

    ``cable_asset_id``, ``cable_mark``, ``length_m``, ``cross_section_mm2``
    обнуляются: линия не должна хранить параметры снятого кабеля. Возвращает
    прежние значения — они попадают в аудит ``cable.returned`` как доказательство
    очистки. ``cable_status="dismounted"`` остаётся явным маркером состояния
    участка (историческая связь не удаляется).
    """
    cleared: dict[str, Any] = {
        "link_id": str(link.id),
        "cable_asset_id": str(link.cable_asset_id) if link.cable_asset_id else None,
        "cable_mark": link.cable_mark,
        "length_m": float(link.length_m) if link.length_m is not None else None,
        "cross_section_mm2": (
            float(link.cross_section_mm2) if link.cross_section_mm2 is not None else None
        ),
    }
    link.cable_asset_id = None
    link.cable_mark = None
    link.length_m = None
    link.cross_section_mm2 = None
    link.cable_status = "dismounted"
    link.updated_by = actor.id
    link.version = (link.version or 1) + 1
    db.flush()
    return cleared


def _denormalize(db: Session, cable: Asset, link: Link, *, cable_mark, length_m, cross_section_mm2) -> None:
    attrs = cable.attrs or {}
    mark = cable_mark or attrs.get("cable_mark")
    if mark:
        link.cable_mark = str(mark)[:64]
    if length_m is not None:
        link.length_m = length_m
    elif attrs.get("length_m") is not None:
        link.length_m = _attr_float(cable, "length_m")
    if cross_section_mm2 is not None:
        link.cross_section_mm2 = cross_section_mm2
    elif attrs.get("section_mm2") is not None:
        link.cross_section_mm2 = _attr_float(cable, "section_mm2")


def _resolve_target_link(db: Session, cable: Asset, target: Asset) -> Link | None:
    """Участок линии, на который ставим кабель при установке «на объект».

    Приоритет: связь кабель ↔ объект → единственная свободная кабельная связь
    объекта. Если связи нет, кабель просто числится установленным на объекте
    (``attrs.installed_on_asset_id``): выдумывать участок линии нельзя.
    """
    link = _link_between(db, cable.id, target.id)
    if link is not None:
        return link

    candidates = [
        item
        for item in _active_links_of(db, target.id)
        if item.link_type in CABLE_LINK_TYPES and item.cable_asset_id is None
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise conflict(
            "У объекта несколько свободных кабельных связей — укажите link_id",
            "cable.link_ambiguous",
        )
    return None


def install(
    db: Session,
    cable: Asset,
    actor: Employee,
    *,
    link_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    cable_mark: str | None = None,
    length_m: float | None = None,
    cross_section_mm2: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Установить кабель: на участок линии (``link_id``) или на объект (``asset_id``)."""
    _require_cable(cable)
    if link_id is None and asset_id is None:
        raise ApiError(
            422,
            "cable.target_required",
            "Укажите link_id (участок линии) или asset_id (объект установки)",
            fields={"link_id": "Укажите link_id или asset_id"},
        )

    attached = list(_links_by_cable(db, [cable.id]).get(cable.id, []))
    target: Asset | None = None
    if link_id is not None:
        link = links_service.get_link(db, link_id)
        if attached and all(item.id != link.id for item in attached):
            raise conflict(
                "Кабель уже установлен на другой связи — сначала снимите его (/return)",
                "cable.already_installed",
            )
    else:
        target = gis.get_asset(db, asset_id)
        if target.id == cable.id:
            raise ApiError(422, "cable.same_asset", "Нельзя установить кабель на самого себя")
        # 1) связь кабель ↔ объект уже есть — ставим на неё;
        # 2) кабель уже стоит на другой связи — требуем сначала снять;
        # 3) иначе — единственная свободная связь объекта либо «на объекте».
        link = _resolve_target_link(db, cable, target)
        if link is None and attached:
            raise conflict(
                "Кабель уже установлен на другой связи — сначала снимите его (/return)",
                "cable.already_installed",
            )

    if link is not None and link.cable_asset_id is not None and link.cable_asset_id != cable.id:
        raise conflict(
            "На этой связи уже установлен другой кабель", "cable.link_occupied"
        )

    previous_status = effective_status(cable)
    if link is not None:
        _denormalize(
            db,
            cable,
            link,
            cable_mark=cable_mark,
            length_m=length_m,
            cross_section_mm2=cross_section_mm2,
        )
        link.cable_asset_id = cable.id
        link.cable_status = "in_work"
        link.updated_by = actor.id
        link.version = (link.version or 1) + 1

    attrs = dict(cable.attrs or {})
    if link is not None:
        attrs["installed_on"] = link.cable_mark or links_service.link_label(link)
        attrs["installed_link_id"] = str(link.id)
        attrs.pop("installed_on_asset_id", None)
    elif target is not None:
        attrs["installed_on"] = target.code
        attrs["installed_on_asset_id"] = str(target.id)
    cable.attrs = attrs
    cable.lifecycle_status = "installed"
    cable.updated_by = actor.id
    cable.version = (cable.version or 1) + 1
    db.commit()
    db.refresh(cable)
    if link is not None:
        db.refresh(link)

    audit.add(
        "cable.installed",
        entity="asset",
        entity_id=cable.id,
        detail=(
            f"Кабель {cable.code} установлен "
            + (
                f"на связь {links_service.link_label(link)}"
                if link is not None
                else f"на объект {target.code}" if target is not None else ""
            )
            + (f" (причина: {reason})" if reason else "")
        ),
        payload={
            "from_status": previous_status,
            "to_status": "installed",
            "link_id": str(link.id) if link is not None else None,
            "asset_id": str(target.id) if target is not None else None,
            "reason": reason,
        },
    )
    return {"cable": cable, "link": link, "asset": target}


def return_to_stock(
    db: Session,
    cable: Asset,
    actor: Employee,
    *,
    status: str = "reserve",
    link_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Снять кабель: ``reserve`` (в запас, по умолчанию) или ``repair``."""
    _require_cable(cable)
    status = (status or "reserve").strip().lower()
    if status not in LIFECYCLE_STATUSES:
        raise ApiError(
            422,
            "validation.failed",
            "Недопустимое состояние кабеля",
            fields={"status": "Допустимо reserve, repair"},
        )

    links = list(_links_by_cable(db, [cable.id]).get(cable.id, []))
    if link_id is not None:
        target_link = links_service.get_link(db, link_id)
        links = [item for item in links if item.id == target_link.id]

    previous_status = effective_status(cable)
    detached: list[uuid.UUID] = []
    cleared: list[dict[str, Any]] = []
    # status="installed" — подтверждение «кабель установлен», а не снятие:
    # связи и их денормализация сохраняются (см. §4.3 отчёта этапа 2).
    if status != "installed":
        for link in links:
            cleared.append(_detach(db, cable, link, actor))
            detached.append(link.id)

    attrs = dict(cable.attrs or {})
    if status != "installed":
        attrs.pop("installed_on", None)
        attrs.pop("installed_link_id", None)
    cable.attrs = attrs
    cable.lifecycle_status = status
    cable.updated_by = actor.id
    cable.version = (cable.version or 1) + 1
    db.commit()
    db.refresh(cable)

    audit.add(
        "cable.returned",
        entity="asset",
        entity_id=cable.id,
        detail=(
            f"Кабель {cable.code}: {previous_status} → {status}"
            + (f", снят со связей: {len(detached)}" if detached else "")
            + (
                ", очищены cable_mark/length_m/cross_section_mm2 у связи"
                if detached
                else ""
            )
            + (f" (причина: {reason})" if reason else "")
        ),
        payload={
            "from_status": previous_status,
            "to_status": status,
            "links": [str(item) for item in detached],
            "reason": reason,
            # F4: фиксируем не только факт снятия, но и очистку денормализации
            # (с прежними значениями — видно, что именно убрано с линии).
            "cleared_fields": list(DETACHED_LINK_FIELDS) if detached else [],
            "cleared": cleared,
        },
    )
    return {
        "cable": cable,
        "link": None,
        "detached_links": detached,
    }
