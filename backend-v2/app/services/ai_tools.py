"""Инструменты для ИИ-агента (MCP): чтение топологии и безопасные изменения.

Все функции принимают сессию БД и сотрудника-исполнителя: MCP-сервер лишь
оборачивает их в протокол, поэтому права проверяются здесь же, как в API.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import Asset, AssetPort, Employee, Link
from app.schemas.gis import AssetUpdate, LinkCreate
from app.services import gis, links as links_service, topology, moves as moves_service
from app.schemas.sync import MoveIn

ALLOWED_ROLES = ("admin", "operator")


def ensure_agent_role(actor: Employee) -> None:
    role = actor.role.code if actor.role else ""
    if role not in ALLOWED_ROLES:
        raise ApiError(403, "mcp.forbidden", f"Роль «{role}» не имеет доступа к инструментам ИИ")


def _serialize_asset(asset: Asset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "code": asset.code,
        "name": asset.name,
        "type": asset.asset_type.name if asset.asset_type else "",
        "type_code": asset.asset_type.code if asset.asset_type else "",
        "status": asset.status,
        "is_mobile": asset.is_mobile,
        "grounded": asset.grounded,
        "x": float(asset.x) if asset.x is not None else None,
        "y": float(asset.y) if asset.y is not None else None,
        "schema_x": float(asset.schema_x) if asset.schema_x is not None else None,
        "schema_y": float(asset.schema_y) if asset.schema_y is not None else None,
        "parent_id": str(asset.parent_asset_id) if asset.parent_asset_id else None,
        "ports": [
            {
                "id": str(port.id),
                "code": port.code,
                "name": port.name,
                "kind": port.kind,
                "voltage_kv": float(port.nominal_voltage_kv) if port.nominal_voltage_kv else None,
            }
            for port in asset.ports
        ],
    }


def _serialize_link(link: Link) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "from_asset": link.from_port.asset.code if link.from_port and link.from_port.asset else None,
        "to_asset": link.to_port.asset.code if link.to_port and link.to_port.asset else None,
        "from_port": link.from_port.code if link.from_port else None,
        "to_port": link.to_port.code if link.to_port else None,
        "link_type": link.link_type,
        "state": link.state,
        "cable_mark": link.cable_mark,
        "length_m": float(link.length_m) if link.length_m else None,
        "label": links_service.link_label(link),
    }


def list_assets(db: Session, actor: Employee) -> list[dict[str, Any]]:
    ensure_agent_role(actor)
    pit = gis.get_pit(db)
    assets = db.scalars(
        select(Asset)
        .where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
        .order_by(Asset.code)
    ).unique().all()
    return [_serialize_asset(asset) for asset in assets]


def list_links(db: Session, actor: Employee) -> list[dict[str, Any]]:
    ensure_agent_role(actor)
    pit = gis.get_pit(db)
    rows = links_service.list_links(db, pit.id)
    return [_serialize_link(link) for link in rows]


def create_link(
    db: Session,
    actor: Employee,
    *,
    from_port_id: uuid.UUID,
    to_port_id: uuid.UUID,
    cable_mark: str | None = None,
    link_type: str = "cable",
) -> dict[str, Any]:
    """Создать связь с проверкой OUT→IN, напряжения и дубликатов (как в API)."""
    ensure_agent_role(actor)
    if link_type not in ("cable", "overhead", "busbar", "jumper", "internal"):
        raise ApiError(422, "mcp.bad_link_type", "Недопустимый тип связи")

    pit = gis.get_pit(db)
    payload = LinkCreate(
        from_port_id=from_port_id,
        to_port_id=to_port_id,
        link_type=link_type,  # type: ignore[arg-type]
        cable_mark=cable_mark,
    )
    created = links_service.create_link(db, pit.id, payload, actor=actor)

    # сервис возвращает LinkOut (pydantic), поэтому собираем ответ вручную
    return {
        "id": str(created.id),
        "from_asset": created.from_asset.code,
        "to_asset": created.to_asset.code,
        "from_port": created.from_port.code,
        "to_port": created.to_port.code,
        "link_type": created.link_type,
        "state": created.state,
        "cable_mark": created.cable_mark,
        "length_m": created.length_m,
        "label": created.label,
    }


def move_asset(
    db: Session, actor: Employee, *, asset_id: uuid.UUID, x: float, y: float, note: str | None = None
) -> dict[str, Any]:
    """Переместить объект: мобильный — с историей, стационарный — сменой координат."""
    ensure_agent_role(actor)
    pit = gis.get_pit(db)
    asset = gis.get_asset(db, asset_id, pit_id=pit.id)
    gis.check_bounds(db, pit.id, x, y)

    if asset.is_mobile:
        move = moves_service.move_asset(
            db,
            asset,
            MoveIn(x=x, y=y, note=note or "перемещено ИИ-агентом"),
            actor=actor,
            source="online",
        )
        return {
            "asset_id": str(asset.id),
            "code": asset.code,
            "x": float(asset.x),
            "y": float(asset.y),
            "history_entry": str(move.id),
            "kind": "move",
        }

    updated = gis.update_asset(db, asset, AssetUpdate(x=x, y=y), actor=actor)
    return {
        "asset_id": str(updated.id),
        "code": updated.code,
        "x": float(updated.x),
        "y": float(updated.y),
        "kind": "patch",
    }


def check_topology(db: Session, actor: Employee) -> list[dict[str, Any]]:
    ensure_agent_role(actor)
    pit = gis.get_pit(db)
    return topology.topology_issues(db, pit.id)


def resolve_actor(db: Session, tab_no: str) -> Employee:
    """Служебная учётная запись, от имени которой работает MCP-сервер."""
    employee = db.scalar(select(Employee).where(Employee.tab_no == tab_no))
    if employee is None or employee.status != "active":
        raise ApiError(401, "mcp.actor_not_found", f"Служебный сотрудник {tab_no} не найден")
    ensure_agent_role(employee)
    return employee
