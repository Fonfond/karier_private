"""Обходы: создание, отметки по объектам, отправка."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError, not_found
from app.models import Asset, Defect, Employee, Inspection, InspectionItem, Media
from app.schemas.ops import AssetRef, InspectionCreate, InspectionItemOut, ItemResultIn
from app.services import audit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _asset_ref(asset: Asset) -> AssetRef:
    return AssetRef(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        type_code=asset.asset_type.code if asset.asset_type else "",
        type_icon=asset.asset_type.icon if asset.asset_type else None,
    )


def create_inspection(
    db: Session, pit_id: uuid.UUID, actor: Employee, payload: InspectionCreate
) -> Inspection:
    asset_ids = list(dict.fromkeys(payload.asset_ids))
    assets: list[Asset] = []
    if asset_ids:
        assets = list(
            db.scalars(
                select(Asset).where(
                    Asset.id.in_(asset_ids),
                    Asset.pit_id == pit_id,
                    Asset.deleted_at.is_(None),
                )
            ).all()
        )
        if len(assets) != len(asset_ids):
            raise ApiError(400, "inspection.assets_invalid", "Часть объектов не найдена")
    else:
        assets = list(
            db.scalars(
                select(Asset)
                .where(Asset.pit_id == pit_id, Asset.deleted_at.is_(None))
                .order_by(Asset.code)
            ).unique().all()
        )

    inspection = Inspection(
        id=uuid.uuid4(),
        pit_id=pit_id,
        employee_id=actor.id,
        kind=payload.kind,
        status="in_progress",
        title=payload.title or f"Обход {_now():%d.%m.%Y %H:%M}",
        note=payload.note,
        started_at=_now(),
    )
    db.add(inspection)
    db.flush()

    for asset in assets:
        db.add(
            InspectionItem(
                id=uuid.uuid4(),
                inspection_id=inspection.id,
                asset_id=asset.id,
            )
        )
    db.commit()
    db.refresh(inspection)

    audit.add(
        "inspection.created",
        entity="inspection",
        entity_id=inspection.id,
        detail=f"Обход на {len(assets)} объектов",
        payload={"assets": len(assets), "kind": payload.kind},
    )
    return inspection


def list_inspections(
    db: Session,
    pit_id: uuid.UUID,
    *,
    employee_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[Inspection]:
    stmt = select(Inspection).where(Inspection.pit_id == pit_id)
    if employee_id is not None:
        stmt = stmt.where(Inspection.employee_id == employee_id)
    if status:
        stmt = stmt.where(Inspection.status == status)
    return list(
        db.scalars(
            stmt.options(selectinload(Inspection.items))
            .order_by(Inspection.started_at.desc())
            .limit(limit)
        ).all()
    )


def get_inspection(
    db: Session, inspection_id: uuid.UUID, *, employee_id: uuid.UUID | None = None
) -> Inspection:
    stmt = select(Inspection).where(Inspection.id == inspection_id)
    if employee_id is not None:
        stmt = stmt.where(Inspection.employee_id == employee_id)
    inspection = db.scalar(stmt.options(selectinload(Inspection.items)))
    if inspection is None:
        raise not_found("Обход не найден")
    return inspection


def set_item_result(
    db: Session, inspection: Inspection, payload: ItemResultIn
) -> InspectionItem:
    if inspection.status in ("submitted", "accepted"):
        raise ApiError(409, "inspection.closed", "Обход уже отправлен — правки запрещены")

    item = db.scalar(
        select(InspectionItem).where(
            InspectionItem.inspection_id == inspection.id,
            InspectionItem.asset_id == payload.asset_id,
        )
    )
    if item is None:
        raise ApiError(400, "inspection.item_not_found", "Объекта нет в этом обходе")

    item.result = payload.result
    item.comment = payload.comment
    item.checked_at = payload.checked_at or _now()
    db.commit()
    db.refresh(item)

    audit.add(
        "inspection.item_checked",
        entity="inspection",
        entity_id=inspection.id,
        detail=f"{item.asset.code}: {payload.result}",
        payload={"asset_id": str(payload.asset_id), "result": payload.result},
    )
    return item


def submit_inspection(db: Session, inspection: Inspection) -> Inspection:
    if inspection.status == "submitted":
        raise ApiError(409, "inspection.already_submitted", "Обход уже отправлен")
    inspection.status = "submitted"
    inspection.finished_at = _now()
    inspection.submitted_at = _now()
    db.commit()
    db.refresh(inspection)

    checked = sum(1 for item in inspection.items if item.result)
    audit.add(
        "inspection.submitted",
        entity="inspection",
        entity_id=inspection.id,
        detail=f"Обход отправлен: проверено {checked} из {len(inspection.items)}",
    )
    return inspection


def inspection_out(db: Session, inspection: Inspection) -> dict:
    media_rows = db.execute(
        select(Media.asset_id, func.count(Media.id))
        .where(Media.inspection_id == inspection.id, Media.deleted_at.is_(None))
        .group_by(Media.asset_id)
    ).all()
    media_by_asset = {asset_id: count for asset_id, count in media_rows}

    defect_rows = db.execute(
        select(Defect.asset_id, func.count(Defect.id))
        .where(Defect.inspection_id == inspection.id)
        .group_by(Defect.asset_id)
    ).all()
    defects_by_asset = {asset_id: count for asset_id, count in defect_rows}

    items = [
        InspectionItemOut(
            id=item.id,
            asset=_asset_ref(item.asset),
            result=item.result,
            comment=item.comment,
            checked_at=item.checked_at,
            media_count=media_by_asset.get(item.asset_id, 0),
        )
        for item in sorted(inspection.items, key=lambda row: row.asset.code)
    ]

    employee = db.get(Employee, inspection.employee_id) if inspection.employee_id else None
    return {
        "id": inspection.id,
        "kind": inspection.kind,
        "status": inspection.status,
        "title": inspection.title,
        "employee_id": inspection.employee_id,
        "employee_name": employee.full_name if employee else None,
        "started_at": inspection.started_at,
        "finished_at": inspection.finished_at,
        "submitted_at": inspection.submitted_at,
        "note": inspection.note,
        "total": len(items),
        "checked": sum(1 for item in items if item.result),
        "defects": sum(defects_by_asset.values()),
        "items": items,
    }
