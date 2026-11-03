"""Дефекты и история объекта."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, not_found
from app.models import (
    Asset,
    Defect,
    Employee,
    Inspection,
    InspectionItem,
    Media,
    SwitchingOp,
)
from app.schemas.ops import AssetRef, DefectCreate, DefectUpdate, HistoryEntry, MediaOut
from app.services import audit
from app.services.media import media_out

SEVERITY_LABEL = {
    "low": "низкая",
    "medium": "средняя",
    "high": "высокая",
    "critical": "критичная",
}

STATUS_LABEL = {
    "open": "открыт",
    "in_progress": "в работе",
    "fixed": "устранён",
    "accepted": "принят",
    "rejected": "отклонён",
}


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


def create_defect(
    db: Session, pit_id: uuid.UUID, actor: Employee, payload: DefectCreate
) -> Defect:
    asset = db.scalar(
        select(Asset).where(Asset.id == payload.asset_id, Asset.deleted_at.is_(None))
    )
    if asset is None or asset.pit_id != pit_id:
        raise ApiError(400, "defect.asset_invalid", "Объект не найден")

    defect = Defect(
        id=uuid.uuid4(),
        pit_id=pit_id,
        asset_id=asset.id,
        inspection_id=payload.inspection_id,
        severity=payload.severity,
        status="open",
        category=payload.category or "other",
        description=payload.description.strip(),
        detected_at=_now(),
        detected_by=actor.id,
        photo_before_id=payload.photo_before_id,
        deadline_at=payload.deadline_at,
    )
    db.add(defect)
    db.commit()
    db.refresh(defect)

    if payload.photo_before_id is not None:
        photo = db.get(Media, payload.photo_before_id)
        if photo is not None:
            photo.defect_id = defect.id
            db.commit()

    audit.add(
        "defect.created",
        entity="defect",
        entity_id=defect.id,
        detail=f"{asset.code}: {SEVERITY_LABEL.get(defect.severity, defect.severity)} — {defect.description[:80]}",
        payload={"severity": defect.severity, "asset_id": str(asset.id)},
    )
    return defect


def list_defects(
    db: Session,
    pit_id: uuid.UUID,
    *,
    status: str | None = None,
    severity: str | None = None,
    asset_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[Defect]:
    stmt = select(Defect).where(Defect.pit_id == pit_id)
    if status:
        stmt = stmt.where(Defect.status == status)
    if severity:
        stmt = stmt.where(Defect.severity == severity)
    if asset_id is not None:
        stmt = stmt.where(Defect.asset_id == asset_id)
    return list(
        db.scalars(stmt.order_by(Defect.detected_at.desc()).limit(limit)).all()
    )


def get_defect(db: Session, defect_id: uuid.UUID) -> Defect:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise not_found("Дефект не найден")
    return defect


def update_defect(
    db: Session, defect: Defect, payload: DefectUpdate, *, actor: Employee
) -> Defect:
    data = payload.model_dump(exclude_unset=True)

    new_status = data.pop("status", None)
    photo_after_id = data.pop("photo_after_id", None)

    for field, value in data.items():
        if value is not None:
            setattr(defect, field, value)

    if photo_after_id is not None:
        photo = db.get(Media, photo_after_id)
        if photo is None:
            raise ApiError(400, "defect.photo_not_found", "Фото не найдено")
        defect.photo_after_id = photo_after_id
        photo.defect_id = defect.id

    if new_status is not None:
        if new_status == "fixed":
            after_id = photo_after_id or defect.photo_after_id
            if after_id is None:
                raise ApiError(
                    422,
                    "defect.photo_required",
                    "Для перевода в «Устранён» нужно фото «после»",
                    fields={"photo_after_id": "Обязательное поле"},
                )
            defect.fixed_at = _now()
            defect.fixed_by = actor.id
        if new_status in ("fixed", "accepted", "rejected"):
            defect.closed_at = _now()
        defect.status = new_status

    db.commit()
    db.refresh(defect)

    audit.add(
        "defect.updated",
        entity="defect",
        entity_id=defect.id,
        detail=f"Статус: {STATUS_LABEL.get(defect.status, defect.status)}",
        payload={"status": defect.status, "changes": payload.model_dump(exclude_unset=True, mode="json")},
    )
    return defect


def _photo(db: Session, media_id: uuid.UUID | None, employee_id: str) -> MediaOut | None:
    if media_id is None:
        return None
    media = db.get(Media, media_id)
    if media is None or media.deleted_at is not None:
        return None
    return MediaOut(**media_out(media, employee_id=employee_id))


def defect_out(db: Session, defect: Defect, *, employee_id: str) -> dict:
    count = db.scalar(
        select(func.count(Media.id)).where(Media.defect_id == defect.id, Media.deleted_at.is_(None))
    )
    detected_by = db.get(Employee, defect.detected_by) if defect.detected_by else None
    fixed_by = db.get(Employee, defect.fixed_by) if defect.fixed_by else None
    return {
        "id": defect.id,
        "asset": _asset_ref(defect.asset),
        "inspection_id": defect.inspection_id,
        "severity": defect.severity,
        "status": defect.status,
        "category": defect.category,
        "description": defect.description,
        "detected_at": defect.detected_at,
        "detected_by_name": detected_by.full_name if detected_by else None,
        "fixed_at": defect.fixed_at,
        "fixed_by_name": fixed_by.full_name if fixed_by else None,
        "photo_before": _photo(db, defect.photo_before_id, employee_id),
        "photo_after": _photo(db, defect.photo_after_id, employee_id),
        "photo_count": int(count or 0),
    }


def asset_history(db: Session, asset: Asset, *, employee_id: str) -> list[HistoryEntry]:
    entries: list[HistoryEntry] = []

    items = db.execute(
        select(InspectionItem, Inspection)
        .join(Inspection, InspectionItem.inspection_id == Inspection.id)
        .where(InspectionItem.asset_id == asset.id, InspectionItem.result.is_not(None))
        .order_by(InspectionItem.checked_at.desc())
        .limit(50)
    ).all()
    for item, inspection in items:
        entries.append(
            HistoryEntry(
                kind="inspection",
                at=item.checked_at or inspection.started_at,
                title=f"Обход: {item.result}",
                detail=item.comment,
                status=inspection.status,
                author=None,
            )
        )

    for defect in db.scalars(
        select(Defect).where(Defect.asset_id == asset.id).order_by(Defect.detected_at.desc()).limit(50)
    ).all():
        entries.append(
            HistoryEntry(
                kind="defect",
                at=defect.detected_at,
                title=f"Дефект: {defect.description[:80]}",
                detail=SEVERITY_LABEL.get(defect.severity, defect.severity),
                status=defect.status,
                severity=defect.severity,
            )
        )

    for media in db.scalars(
        select(Media)
        .where(Media.asset_id == asset.id, Media.deleted_at.is_(None))
        .order_by(Media.captured_at.desc())
        .limit(50)
    ).all():
        entries.append(
            HistoryEntry(
                kind="media",
                at=media.captured_at or media.received_at,
                title="Фото",
                detail=media.author_name,
                media_id=media.id,
                author=media.author_tab_no,
            )
        )

    for op in db.scalars(
        select(SwitchingOp)
        .where(SwitchingOp.asset_id == asset.id)
        .order_by(SwitchingOp.performed_at.desc())
        .limit(50)
    ).all():
        entries.append(
            HistoryEntry(
                kind="switching",
                at=op.performed_at,
                title=f"Переключение: {op.action}",
                detail=op.reason,
                status=op.to_state,
            )
        )

    entries.sort(key=lambda entry: entry.at, reverse=True)
    return entries[:100]
