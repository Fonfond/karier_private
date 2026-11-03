"""Служебные эндпоинты."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import HealthOut

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Процесс жив")
def live() -> dict:
    return {"status": "ok"}


@router.get("/ready", response_model=HealthOut, summary="Готовность (БД доступна)")
def ready(db: Session = Depends(get_db)) -> HealthOut:
    db.execute(text("select 1"))
    return HealthOut(status="ok", service="karier-api", version="0.1.0", database="ok")
