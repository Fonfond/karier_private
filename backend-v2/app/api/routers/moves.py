"""Перемещение мобильных объектов."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.db.session import get_db
from app.models import Employee
from app.schemas.sync import MoveIn, MoveListOut, MoveOut
from app.services import gis, moves as moves_service

router = APIRouter(tags=["moves"])


@router.post("/assets/{asset_id}/move", response_model=MoveOut, summary="Переместить объект")
def move_asset(
    asset_id: uuid.UUID,
    payload: MoveIn,
    user: Employee = Depends(require_permission("asset.move")),
    db: Session = Depends(get_db),
) -> MoveOut:
    asset = gis.get_asset(db, asset_id)
    move = moves_service.move_asset(
        db, asset, payload, actor=user, source=payload.source
    )
    return MoveOut(**moves_service.move_out(db, move))


@router.get("/assets/{asset_id}/moves", response_model=MoveListOut, summary="История перемещений")
def list_moves(
    asset_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> MoveListOut:
    gis.get_asset(db, asset_id)
    rows = moves_service.list_moves(db, asset_id, limit=limit)
    return MoveListOut(items=[MoveOut(**moves_service.move_out(db, row)) for row in rows], total=len(rows))
