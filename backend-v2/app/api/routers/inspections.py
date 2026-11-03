"""Обходы: создание, отметки, отправка."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.errors import forbidden
from app.db.session import get_db
from app.models import Employee
from app.schemas.ops import (
    InspectionCreate,
    InspectionListOut,
    InspectionOut,
    ItemResultIn,
)
from app.services import gis, inspections as inspections_service
from app.services.auth import permissions_of

router = APIRouter(prefix="/inspections", tags=["inspections"])


@router.post("", response_model=InspectionOut, status_code=201, summary="Начать обход")
def create_inspection(
    payload: InspectionCreate,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> InspectionOut:
    pit = gis.get_pit(db)
    inspection = inspections_service.create_inspection(db, pit.id, user, payload)
    return InspectionOut(**inspections_service.inspection_out(db, inspection))


@router.get("", response_model=InspectionListOut, summary="Список обходов")
def list_inspections(
    mine: bool = Query(default=False),
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> InspectionListOut:
    pit = gis.get_pit(db)
    rows = inspections_service.list_inspections(
        db, pit.id, employee_id=user.id if mine else None, status=status, limit=limit
    )
    return InspectionListOut(
        items=[InspectionOut(**inspections_service.inspection_out(db, row)) for row in rows],
        total=len(rows),
    )


@router.get("/{inspection_id}", response_model=InspectionOut, summary="Обход с объектами")
def get_inspection(
    inspection_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> InspectionOut:
    inspection = inspections_service.get_inspection(db, inspection_id)
    return InspectionOut(**inspections_service.inspection_out(db, inspection))


@router.post("/{inspection_id}/items", response_model=InspectionOut, summary="Отметить объект")
def set_item(
    inspection_id: uuid.UUID,
    payload: ItemResultIn,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> InspectionOut:
    inspection = inspections_service.get_inspection(db, inspection_id)
    if inspection.employee_id not in (None, user.id) and "audit.view" not in permissions_of(user):
        raise forbidden("Можно отмечать только свой обход")
    inspections_service.set_item_result(db, inspection, payload)
    db.refresh(inspection)
    return InspectionOut(**inspections_service.inspection_out(db, inspection))


@router.post("/{inspection_id}/submit", response_model=InspectionOut, summary="Завершить обход")
def submit_inspection(
    inspection_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> InspectionOut:
    inspection = inspections_service.get_inspection(db, inspection_id)
    if inspection.employee_id not in (None, user.id):
        raise forbidden("Можно отправить только свой обход")
    updated = inspections_service.submit_inspection(db, inspection)
    return InspectionOut(**inspections_service.inspection_out(db, updated))
