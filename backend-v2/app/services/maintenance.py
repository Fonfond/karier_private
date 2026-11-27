"""Журнал ТО: моточасы, топливо, ремонты."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, not_found
from app.models import Asset, Employee, MaintenanceEntry
from app.schemas.gis import MaintenanceIn


def _out(entry: MaintenanceEntry) -> dict:
    return {
        "id": entry.id,
        "asset_id": entry.asset_id,
        "at": entry.at,
        "kind": entry.kind,
        "motor_hours": float(entry.motor_hours) if entry.motor_hours is not None else None,
        "fuel_liters": float(entry.fuel_liters) if entry.fuel_liters is not None else None,
        "fuel_level_pct": float(entry.fuel_level_pct) if entry.fuel_level_pct is not None else None,
        "cost": float(entry.cost) if entry.cost is not None else None,
        "note": entry.note,
        "author_name": entry.author.full_name if getattr(entry, "author", None) else None,
    }


def list_entries(db: Session, asset: Asset, limit: int = 100) -> list[dict]:
    rows = db.scalars(
        select(MaintenanceEntry)
        .where(MaintenanceEntry.asset_id == asset.id)
        .order_by(MaintenanceEntry.at.desc())
        .limit(limit)
    ).all()
    return [_out(row) for row in rows]


def add_entry(db: Session, asset: Asset, actor: Employee, payload: MaintenanceIn) -> dict:
    if not asset.asset_type.has_maintenance:
        raise ApiError(400, "maintenance.not_enabled", "Для этого типа не включён журнал ТО")
    entry = MaintenanceEntry(
        id=uuid.uuid4(),
        asset_id=asset.id,
        at=payload.at or datetime.now(timezone.utc),
        kind=payload.kind,
        motor_hours=payload.motor_hours,
        fuel_liters=payload.fuel_liters,
        fuel_level_pct=payload.fuel_level_pct,
        cost=payload.cost,
        note=payload.note,
        author_id=actor.id,
    )
    db.add(entry)
    if payload.motor_hours is not None:
        asset.attrs = {**(asset.attrs or {}), "motor_hours": payload.motor_hours}
    if payload.fuel_level_pct is not None:
        asset.attrs = {**(asset.attrs or {}), "fuel_level_pct": payload.fuel_level_pct}
    db.commit()
    db.refresh(entry)
    return _out(entry)


def delete_entry(db: Session, entry_id: uuid.UUID, actor: Employee) -> None:
    entry = db.get(MaintenanceEntry, entry_id)
    if entry is None:
        raise not_found("Запись журнала не найдена")
    db.delete(entry)
    db.commit()
