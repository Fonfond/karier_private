"""Дефекты и история объекта."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_admin, require_permission
from app.db.session import get_db
from app.models import Employee
from app.schemas.ops import (
    DefectCreate,
    DefectListOut,
    DefectOut,
    DefectUpdate,
    HistoryOut,
)
from app.services import defects as defects_service
from app.services import gis

router = APIRouter(tags=["defects"])


@router.post("/defects", response_model=DefectOut, status_code=201, summary="Зафиксировать дефект")
def create_defect(
    payload: DefectCreate,
    user: Employee = Depends(require_permission("defect.manage")),
    db: Session = Depends(get_db),
) -> DefectOut:
    pit = gis.get_pit(db)
    defect = defects_service.create_defect(db, pit.id, user, payload)
    return DefectOut(**defects_service.defect_out(db, defect, employee_id=str(user.id)))


@router.get("/defects", response_model=DefectListOut, summary="Список дефектов")
def list_defects(
    status: str | None = Query(default=None, max_length=16),
    severity: str | None = Query(default=None, max_length=16),
    asset_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> DefectListOut:
    pit = gis.get_pit(db)
    rows = defects_service.list_defects(
        db, pit.id, status=status, severity=severity, asset_id=asset_id, limit=limit
    )
    return DefectListOut(
        items=[DefectOut(**defects_service.defect_out(db, row, employee_id=str(user.id))) for row in rows],
        total=len(rows),
    )


@router.delete(
    "/defects/{defect_id}",
    summary="Удалить дефект (мягко, только админ)",
)
def delete_defect(
    defect_id: uuid.UUID,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    defect = defects_service.get_defect(db, defect_id)
    defects_service.delete_defect(db, defect, actor=admin)
    return {"message": "Дефект удалён", "id": str(defect_id)}


@router.get("/defects/{defect_id}", response_model=DefectOut, summary="Карточка дефекта")
def get_defect(
    defect_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> DefectOut:
    defect = defects_service.get_defect(db, defect_id)
    return DefectOut(**defects_service.defect_out(db, defect, employee_id=str(user.id)))


@router.patch("/defects/{defect_id}", response_model=DefectOut, summary="Изменить дефект")
def update_defect(
    defect_id: uuid.UUID,
    payload: DefectUpdate,
    user: Employee = Depends(require_permission("defect.manage")),
    db: Session = Depends(get_db),
) -> DefectOut:
    defect = defects_service.get_defect(db, defect_id)
    updated = defects_service.update_defect(db, defect, payload, actor=user)
    return DefectOut(**defects_service.defect_out(db, updated, employee_id=str(user.id)))


@router.get("/assets/{asset_id}/history", response_model=HistoryOut, summary="История объекта")
def asset_history(
    asset_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> HistoryOut:
    asset = gis.get_asset(db, asset_id)
    entries = defects_service.asset_history(db, asset, employee_id=str(user.id))
    return HistoryOut(asset_id=asset.id, items=entries)
