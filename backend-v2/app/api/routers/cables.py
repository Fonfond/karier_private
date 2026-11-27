"""Кабельный учёт этапа 2: список, установка на линию, снятие в запас/ремонт."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.db.session import get_db
from app.models import Employee
from app.schemas.equipment import (
    CableInstallIn,
    CableInstallOut,
    CableOut,
    CableReturnIn,
    CableReturnOut,
    CableStatusLiteral,
)
from app.services import cables as cables_service
from app.services import links as links_service

router = APIRouter(prefix="/cables", tags=["cables"])


@router.get("", response_model=list[CableOut], summary="Кабели: установлены / в запасе / в ремонте")
def list_cables(
    lifecycle_status: CableStatusLiteral | None = Query(
        default=None, description="installed | reserve | repair"
    ),
    q: str | None = Query(default=None, max_length=128, description="Поиск по коду или названию"),
    limit: int = Query(default=200, ge=1, le=1000, description="Сколько строк вернуть"),
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[CableOut]:
    rows = cables_service.list_cables(
        db, lifecycle_status=lifecycle_status, q=q, limit=limit
    )
    return [CableOut(**row) for row in rows]


@router.post(
    "/{cable_id}/install",
    response_model=CableInstallOut,
    summary="Установить кабель на линию (link_id) или объект (asset_id)",
)
def install_cable(
    cable_id: uuid.UUID,
    payload: CableInstallIn,
    user: Employee = Depends(require_permission("asset.status.edit")),
    db: Session = Depends(get_db),
) -> CableInstallOut:
    cable = cables_service.get_cable(db, cable_id)
    result = cables_service.install(
        db,
        cable,
        user,
        link_id=payload.link_id,
        asset_id=payload.asset_id,
        cable_mark=payload.cable_mark,
        length_m=payload.length_m,
        cross_section_mm2=payload.cross_section_mm2,
        reason=payload.reason,
    )
    link = result["link"]
    cable = result["cable"]
    return CableInstallOut(
        cable=CableOut(**cables_service.cable_out(cable, link)),
        link_id=link.id if link is not None else None,
        link_label=links_service.link_label(link) if link is not None else None,
    )


@router.post(
    "/{cable_id}/return",
    response_model=CableReturnOut,
    summary="Снять кабель в запас (reserve) или в ремонт (repair)",
)
def return_cable(
    cable_id: uuid.UUID,
    payload: CableReturnIn | None = None,
    user: Employee = Depends(require_permission("asset.status.edit")),
    db: Session = Depends(get_db),
) -> CableReturnOut:
    cable = cables_service.get_cable(db, cable_id)
    data = payload or CableReturnIn()
    result = cables_service.return_to_stock(
        db,
        cable,
        user,
        status=data.status,
        link_id=data.link_id,
        reason=data.reason,
    )
    return CableReturnOut(
        cable=CableOut(**cables_service.cable_out(result["cable"])),
        detached_links=result["detached_links"],
    )
