"""Журнал аудита (только право audit.view)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import AuditLog, Employee
from app.schemas.audit import AuditListOut, AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])

Permission = Depends(require_permission("audit.view"))


@router.get("", response_model=AuditListOut, summary="Записи журнала")
def list_audit(
    actor_tab_no: str | None = Query(default=None, max_length=16),
    action: str | None = Query(default=None, max_length=64),
    entity: str | None = Query(default=None, max_length=48),
    result: str | None = Query(default=None, pattern="^(ok|denied|error)$"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Employee = Permission,
    db: Session = Depends(get_db),
) -> AuditListOut:
    stmt = select(AuditLog)
    if actor_tab_no:
        stmt = stmt.where(AuditLog.actor_tab_no == actor_tab_no)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if date_from:
        stmt = stmt.where(AuditLog.at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.at <= date_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return AuditListOut(items=[AuditOut.model_validate(r) for r in rows], total=total)
