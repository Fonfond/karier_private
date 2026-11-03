"""Фото и медиа: сохранение, метаданные, выдача."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError, not_found
from app.core.security import create_media_token
from app.models import Asset, Media
from app.services import audit
from app.services.storage import storage

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

PURPOSE_LABEL = {
    "inspection": "Осмотр",
    "defect": "Дефект",
    "install": "Монтаж",
    "move_proof": "Перемещение",
    "passport": "Паспорт",
    "other": "Прочее",
}


def save_photo(
    db: Session,
    asset: Asset,
    *,
    upload: UploadFile,
    actor,
    purpose: str = "inspection",
    captured_at: datetime | None = None,
    lat: float | None = None,
    lon: float | None = None,
    accuracy_m: float | None = None,
    geo_source: str = "none",
    exif: dict | None = None,
    width: int | None = None,
    height: int | None = None,
    watermark: str | None = None,
    inspection_id: uuid.UUID | None = None,
    defect_id: uuid.UUID | None = None,
) -> Media:
    mime = (upload.content_type or "image/jpeg").split(";")[0].strip()
    if mime not in ALLOWED_IMAGE_MIME:
        raise ApiError(415, "media.bad_type", "Поддерживаются только изображения (JPEG, PNG, WebP, HEIC)")

    data = upload.file.read()
    limit = settings.MAX_PHOTO_MB * 1024 * 1024
    if len(data) > limit:
        raise ApiError(413, "media.too_large", f"Фото больше {settings.MAX_PHOTO_MB} МБ")
    if not data:
        raise ApiError(400, "media.empty", "Пустой файл")

    media_id = uuid.uuid4()
    suffix = Path(upload.filename or "").suffix.lower()[:8] or ".jpg"
    key = f"{asset.pit_id}/{media_id}{suffix}"
    stored = storage.save(data, key=key)

    media = Media(
        id=media_id,
        pit_id=asset.pit_id,
        asset_id=asset.id,
        inspection_id=inspection_id,
        defect_id=defect_id,
        kind="photo",
        purpose=purpose,
        storage_path=key,
        mime=mime,
        size_bytes=stored.size,
        width=width,
        height=height,
        sha256=stored.sha256,
        captured_at=captured_at or datetime.now(timezone.utc),
        lat=lat,
        lon=lon,
        accuracy_m=accuracy_m,
        geo_source=geo_source,
        author_id=actor.id,
        author_tab_no=actor.tab_no,
        author_name=actor.full_name,
        watermark_applied=watermark,
        exif=exif or {},
        sync_state="ready",
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    audit.add(
        "media.uploaded",
        entity="media",
        entity_id=media.id,
        detail=(
            f"{PURPOSE_LABEL.get(purpose, purpose)}: {asset.code}, "
            f"автор {actor.tab_no}, sha256 {stored.sha256[:12]}…"
        ),
        payload={"size": stored.size, "geo_source": geo_source, "mime": mime},
    )
    return media


def list_media(
    db: Session,
    *,
    asset_id: uuid.UUID | None = None,
    defect_id: uuid.UUID | None = None,
    inspection_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[Media]:
    stmt = select(Media).where(Media.deleted_at.is_(None))
    if asset_id is not None:
        stmt = stmt.where(Media.asset_id == asset_id)
    if defect_id is not None:
        stmt = stmt.where(Media.defect_id == defect_id)
    if inspection_id is not None:
        stmt = stmt.where(Media.inspection_id == inspection_id)
    return list(db.scalars(stmt.order_by(Media.captured_at.desc()).limit(limit)).all())


def get_media(db: Session, media_id: uuid.UUID) -> Media:
    media = db.get(Media, media_id)
    if media is None or media.deleted_at is not None:
        raise not_found("Фото не найдено")
    return media


def delete_media(db: Session, media: Media, *, actor, is_admin: bool) -> None:
    if not is_admin and media.author_id != actor.id:
        raise ApiError(403, "media.forbidden", "Удалять можно только свои фото")
    media.deleted_at = datetime.now(timezone.utc)
    media.deleted_by = actor.id
    db.commit()
    try:
        storage.delete(media.storage_path)
    except Exception:  # noqa: BLE001 — файл мог быть уже удалён
        pass
    audit.add("media.deleted", entity="media", entity_id=media.id, detail="Удалено фото")


def media_out(media: Media, *, employee_id: str) -> dict:
    token = create_media_token(str(media.id), employee_id=employee_id)
    return {
        "id": media.id,
        "asset_id": media.asset_id,
        "inspection_id": media.inspection_id,
        "defect_id": media.defect_id,
        "kind": media.kind,
        "purpose": media.purpose,
        "mime": media.mime,
        "size_bytes": media.size_bytes,
        "width": media.width,
        "height": media.height,
        "sha256": media.sha256,
        "captured_at": media.captured_at,
        "received_at": media.received_at,
        "lat": float(media.lat) if media.lat is not None else None,
        "lon": float(media.lon) if media.lon is not None else None,
        "accuracy_m": float(media.accuracy_m) if media.accuracy_m is not None else None,
        "geo_source": media.geo_source,
        "author_tab_no": media.author_tab_no,
        "author_name": media.author_name,
        "watermark_applied": media.watermark_applied,
        "content_url": f"/api/media/{media.id}/file?token={token}",
        "exif": media.exif or {},
    }


def file_response_payload(media: Media) -> tuple[str, str]:
    """Вернуть (storage_path, mime) — роутер решает, отдать файл или редирект."""
    return media.storage_path, media.mime
