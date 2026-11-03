"""Синхронизация: push, pull, конфликты."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.models import Employee
from app.schemas.sync import ConflictListOut, ConflictOut, PullOut, PushIn, PushOut
from app.services import gis, sync as sync_service

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/push", response_model=PushOut, summary="Отправить офлайн-операции")
def push(
    payload: PushIn,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> PushOut:
    try:
        result = sync_service.push(db, user, payload)
    finally:
        sync_service.reset_actor(db)
    return PushOut(**result)


@router.get("/pull", response_model=PullOut, summary="Дельта изменений с сервера")
def pull(
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> PullOut:
    return PullOut(**sync_service.pull(db, since, limit))


@router.get("/conflicts", response_model=ConflictListOut, summary="Журнал конфликтов")
def list_conflicts(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConflictListOut:
    rows = sync_service.conflicts(db)
    return ConflictListOut(
        items=[ConflictOut(**sync_service.conflict_out(db, row)) for row in rows],
        total=len(rows),
    )


@router.get("/state", summary="Состояние синхронизации карьера")
def state(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    pit = gis.get_pit(db)
    from sqlalchemy import func, select

    from app.models import ChangeLog, Conflict

    last_seq = db.scalar(select(func.max(ChangeLog.seq))) or 0
    conflicts_count = db.scalar(select(func.count(Conflict.id))) or 0
    return {"last_seq": int(last_seq), "conflicts": int(conflicts_count), "pit_id": str(pit.id)}
