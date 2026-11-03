"""Дашборд и выгрузки: Excel и PDF по короткоживущей ссылке."""

from __future__ import annotations

import io
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.core.errors import ApiError
from app.core.security import create_export_token, decode_token
from app.db.session import get_db
from app.models import Employee
from app.services import analytics, gis, reports
from app.services.auth import permissions_of

router = APIRouter(tags=["reports"])

ExportKind = Literal["assets", "defects", "switching", "inspections", "passport"]

FILENAMES = {
    "assets": ("assets.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "defects": ("defects.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "switching": ("switching.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "inspections": ("inspections.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "passport": ("passport.pdf", "application/pdf"),
}


class ExportTokenIn(BaseModel):
    kind: ExportKind
    asset_id: uuid.UUID | None = None


@router.get("/dashboard/summary", summary="Метрики для дашборда")
def dashboard_summary(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    pit = gis.get_pit(db)
    summary = analytics.dashboard_summary(db, pit)
    summary.pop("asset_ids", None)
    return summary


@router.post("/reports/token", summary="Ссылка на выгрузку (Excel/PDF)")
def create_export_link(
    payload: ExportTokenIn,
    user: Employee = Depends(require_permission("report.export")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.kind == "passport" and payload.asset_id is None:
        raise ApiError(422, "report.asset_required", "Для паспорта нужен объект")

    if payload.kind == "passport" and payload.asset_id is not None:
        gis.get_asset(db, payload.asset_id)

    token = create_export_token(
        payload.kind,
        employee_id=str(user.id),
        asset_id=str(payload.asset_id) if payload.asset_id else None,
    )
    return {"url": f"/api/reports/export?token={token}", "kind": payload.kind}


@router.get("/reports/export", summary="Скачать выгрузку по короткоживущей ссылке")
def download_export(
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    try:
        payload = decode_token(token, "export")
    except Exception as exc:  # noqa: BLE001
        raise ApiError(401, "report.bad_token", "Ссылка на отчёт истекла — сформируйте новую") from exc

    employee = db.get(Employee, payload.get("employee_id")) if payload.get("employee_id") else None
    if employee is None or employee.status != "active":
        raise ApiError(401, "report.bad_token", "Пользователь недоступен")
    if "report.export" not in permissions_of(employee):
        raise ApiError(403, "perm.denied", "Нет права на выгрузку отчётов")

    kind = payload.get("sub")
    if kind not in FILENAMES:
        raise ApiError(400, "report.unknown", "Неизвестный тип отчёта")

    pit = gis.get_pit(db)
    if kind == "assets":
        data = reports.assets_xlsx(db, pit)
    elif kind == "defects":
        data = reports.defects_xlsx(db, pit)
    elif kind == "switching":
        data = reports.switching_xlsx(db, pit)
    elif kind == "inspections":
        data = reports.inspections_xlsx(db, pit)
    else:
        asset_id = payload.get("asset_id")
        if not asset_id:
            raise ApiError(422, "report.asset_required", "В ссылке нет объекта")
        asset = gis.get_asset(db, uuid.UUID(str(asset_id)))
        data = reports.passport_pdf(db, asset, generated_by=employee)

    filename, media_type = FILENAMES[kind]
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
