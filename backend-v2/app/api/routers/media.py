"""Фото: загрузка, список, выдача файла, удаление."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Employee, Media
from app.schemas.ops import MediaListOut, MediaOut
from app.services import gis, media as media_service
from app.services.storage import storage
from app.services.auth import permissions_of

router = APIRouter(tags=["media"])


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(422, "media.bad_datetime", "Некорректная дата съёмки") from exc


@router.post(
    "/assets/{asset_id}/media",
    response_model=MediaOut,
    status_code=201,
    summary="Загрузить фото объекта",
)
def upload_media(
    asset_id: uuid.UUID,
    file: UploadFile = File(...),
    purpose: str = Form("inspection"),
    captured_at: str | None = Form(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    accuracy_m: float | None = Form(None),
    geo_source: str = Form("none"),
    width: int | None = Form(None),
    height: int | None = Form(None),
    watermark: str | None = Form(None),
    exif: str | None = Form(None),
    inspection_id: uuid.UUID | None = Form(None),
    defect_id: uuid.UUID | None = Form(None),
    user: Employee = Depends(require_permission("media.create")),
    db: Session = Depends(get_db),
) -> MediaOut:
    asset = gis.get_asset(db, asset_id)
    exif_payload: dict[str, Any] = {}
    if exif:
        try:
            exif_payload = json.loads(exif)
        except json.JSONDecodeError:
            exif_payload = {"raw": exif[:2000]}

    media = media_service.save_photo(
        db,
        asset,
        upload=file,
        actor=user,
        purpose=purpose,
        captured_at=_parse_dt(captured_at),
        lat=lat,
        lon=lon,
        accuracy_m=accuracy_m,
        geo_source=geo_source,
        exif=exif_payload,
        width=width,
        height=height,
        watermark=watermark,
        inspection_id=inspection_id,
        defect_id=defect_id,
    )
    return MediaOut(**media_service.media_out(media, employee_id=str(user.id)))


@router.get("/assets/{asset_id}/media", response_model=MediaListOut, summary="Фото объекта")
def list_asset_media(
    asset_id: uuid.UUID,
    purpose: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=100, ge=1, le=300),
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> MediaListOut:
    gis.get_asset(db, asset_id)
    rows = [
        row
        for row in media_service.list_media(db, asset_id=asset_id, limit=limit)
        if purpose is None or row.purpose == purpose
    ]
    return MediaListOut(
        items=[MediaOut(**media_service.media_out(row, employee_id=str(user.id))) for row in rows],
        total=len(rows),
    )


@router.get("/media/{media_id}/file", summary="Файл фото по короткой ссылке")
def download_media(
    media_id: uuid.UUID,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    media = media_service.get_media(db, media_id)
    try:
        payload = decode_token(token, "media")
    except Exception as exc:  # noqa: BLE001
        raise ApiError(401, "media.bad_token", "Ссылка на фото истекла") from exc
    if payload.get("sub") != str(media.id):
        raise ApiError(403, "media.forbidden", "Ссылка не соответствует фото")

    if storage.backend == "local":
        path = storage.path(media.storage_path)
        if not path.exists():
            raise ApiError(404, "media.file_missing", "Файл не найден в хранилище")
        return FileResponse(path, media_type=media.mime)
    return RedirectResponse(url=f"{settings.BLOB_PUBLIC_BASE.rstrip('/')}/{media.storage_path}")


@router.delete("/media/{media_id}", summary="Удалить фото")
def delete_media(
    media_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    media = media_service.get_media(db, media_id)
    is_admin = "document.manage" in permissions_of(user)
    media_service.delete_media(db, media, actor=user, is_admin=is_admin)
    return {"message": "Фото удалено", "id": str(media_id)}
