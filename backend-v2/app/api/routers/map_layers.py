"""Подложки карты: загрузка новой карты и выдача изображения."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.core.errors import ApiError, not_found
from app.db.session import get_db
from app.models import Employee, MapLayer
from app.schemas.gis import MapLayerOut
from app.services import gis
from app.services.storage import storage

router = APIRouter(prefix="/map", tags=["map"])

MAX_LAYER_MB = 40
ALLOWED = {"image/png", "image/jpeg", "image/webp"}


@router.get("/layers", response_model=list[MapLayerOut], summary="Все подложки карьера")
def list_layers(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[MapLayerOut]:
    pit = gis.get_pit(db)
    rows = db.scalars(
        select(MapLayer).where(MapLayer.pit_id == pit.id).order_by(MapLayer.version.desc())
    ).all()
    return [gis.layer_out(row) for row in rows]


@router.post(
    "/layers",
    response_model=MapLayerOut,
    status_code=201,
    summary="Загрузить новую карту (админ)",
)
async def upload_layer(
    file: UploadFile = File(..., description="PNG/JPEG/WebP с изображением карты"),
    name: str = Form(default="Новая карта"),
    meters_per_pixel: float = Form(default=0.5),
    origin_x: float = Form(default=0.0),
    origin_y: float = Form(default=0.0),
    admin: Employee = Depends(require_permission("settings.edit")),
    db: Session = Depends(get_db),
) -> MapLayerOut:
    if (file.content_type or "") not in ALLOWED:
        raise ApiError(422, "map.bad_type", "Поддерживаются PNG, JPEG и WebP")

    data = await file.read()
    if not data:
        raise ApiError(422, "map.empty", "Файл пустой")
    if len(data) > MAX_LAYER_MB * 1024 * 1024:
        raise ApiError(422, "map.too_large", f"Файл больше {MAX_LAYER_MB} МБ")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        width_px, height_px = image.size
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        normalized = io.BytesIO()
        image.save(normalized, format="PNG", optimize=True)
        payload = normalized.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(422, "map.bad_image", "Не удалось прочитать изображение") from exc

    pit = gis.get_pit(db)
    layer = gis.create_map_layer(
        db,
        pit.id,
        name=name.strip() or "Новая карта",
        data=payload,
        width_px=width_px,
        height_px=height_px,
        meters_per_pixel=meters_per_pixel,
        origin_x=origin_x,
        origin_y=origin_y,
        actor_id=admin.id,
    )
    return gis.layer_out(layer)


@router.get("/layers/{layer_id}/image", summary="Изображение подложки (только авторизованным)")
def layer_image(
    layer_id: uuid.UUID,
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    layer = db.get(MapLayer, layer_id)
    if layer is None:
        raise not_found("Подложка не найдена")
    try:
        data = storage.read(f"maps/{layer.id}.png")
    except Exception as exc:  # noqa: BLE001
        raise not_found("Файл подложки недоступен") from exc
    return Response(
        content=data,
        media_type="image/png",
        # S-5: подложка — не публичный ресурс; кэш только в пределах сеанса клиента.
        headers={"Cache-Control": "private, no-store"},
    )
