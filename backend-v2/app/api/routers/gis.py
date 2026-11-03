"""ГИС-реестр: типы объектов, объекты, порты, подложка, путь питания."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.core.errors import not_found
from app.db.session import get_db
from app.models import AssetType, Employee
from app.schemas.gis import (
    AssetBriefOut,
    AssetCreate,
    AssetListOut,
    AssetOut,
    AssetTypeCreate,
    AssetTypeOut,
    AssetUpdate,
    MapLayerOut,
    PowerPathOut,
)
from app.services import audit, gis

router = APIRouter(tags=["gis"])


# --- типы объектов ---------------------------------------------------------

@router.get("/asset-types", response_model=list[AssetTypeOut], summary="Справочник типов")
def list_asset_types(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[AssetTypeOut]:
    return [AssetTypeOut.model_validate(item) for item in gis.list_types(db)]


@router.post(
    "/asset-types",
    response_model=AssetTypeOut,
    status_code=201,
    summary="Добавить тип (админ)",
)
def create_asset_type(
    payload: AssetTypeCreate,
    admin: Employee = Depends(require_permission("settings.edit")),
    db: Session = Depends(get_db),
) -> AssetTypeOut:
    asset_type = gis.create_type(db, payload)
    audit.add(
        "asset_type.created",
        entity="asset_type",
        entity_id=asset_type.id,
        detail=f"Добавлен тип {asset_type.code}",
        payload={"code": asset_type.code, "category": asset_type.category},
    )
    return AssetTypeOut.model_validate(asset_type)


@router.patch(
    "/asset-types/{type_id}",
    response_model=AssetTypeOut,
    summary="Изменить тип (админ)",
)
def patch_asset_type(
    type_id: uuid.UUID,
    payload: dict[str, Any],
    _: Employee = Depends(require_permission("settings.edit")),
    db: Session = Depends(get_db),
) -> AssetTypeOut:
    asset_type = db.get(AssetType, type_id)
    if asset_type is None:
        raise not_found("Тип не найден")
    updated = gis.update_type(db, asset_type, payload)
    audit.add(
        "asset_type.updated",
        entity="asset_type",
        entity_id=updated.id,
        detail=f"Изменён тип {updated.code}",
    )
    return AssetTypeOut.model_validate(updated)


# --- объекты ---------------------------------------------------------------

@router.get("/assets", response_model=AssetListOut, summary="Список объектов")
def list_assets(
    q: str | None = Query(default=None, max_length=128),
    type_code: str | None = Query(default=None, max_length=48),
    status: str | None = Query(default=None, max_length=24),
    is_mobile: bool | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> AssetListOut:
    pit = gis.get_pit(db)
    rows, total = gis.list_assets(
        db,
        pit_id=pit.id,
        q=q,
        type_code=type_code,
        status=status,
        is_mobile=is_mobile,
        limit=limit,
        offset=offset,
    )
    return AssetListOut(items=[gis.asset_brief(a) for a in rows], total=total)


@router.post("/assets", response_model=AssetOut, status_code=201, summary="Создать объект")
def create_asset(
    payload: AssetCreate,
    user: Employee = Depends(require_permission("asset.create")),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = gis.create_asset(db, payload, actor=user)
    audit.add(
        "asset.created",
        entity="asset",
        entity_id=asset.id,
        detail=f"Создан объект {asset.code} ({asset.name})",
        payload={"code": asset.code, "type": asset.asset_type.code, "x": float(asset.x), "y": float(asset.y)}
        if asset.x is not None and asset.y is not None
        else {"code": asset.code, "type": asset.asset_type.code},
    )
    return gis.asset_full(asset)


@router.get("/assets/{asset_id}", response_model=AssetOut, summary="Карточка объекта")
def get_asset(
    asset_id: uuid.UUID,
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = gis.get_asset(db, asset_id)
    return gis.asset_full(asset)


@router.patch("/assets/{asset_id}", response_model=AssetOut, summary="Изменить объект")
def patch_asset(
    asset_id: uuid.UUID,
    payload: AssetUpdate,
    user: Employee = Depends(require_permission("asset.create")),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = gis.get_asset(db, asset_id)
    before = {
        "name": asset.name,
        "status": asset.status,
        "x": float(asset.x) if asset.x is not None else None,
        "y": float(asset.y) if asset.y is not None else None,
        "version": asset.version,
    }
    updated = gis.update_asset(db, asset, payload, actor=user)
    audit.add(
        "asset.updated",
        entity="asset",
        entity_id=updated.id,
        detail=f"Изменён объект {updated.code}",
        payload={"before": before, "changes": payload.model_dump(exclude_unset=True, mode="json")},
    )
    return gis.asset_full(updated)


@router.delete("/assets/{asset_id}", summary="Удалить объект (мягко)")
def delete_asset(
    asset_id: uuid.UUID,
    user: Employee = Depends(require_permission("asset.delete")),
    db: Session = Depends(get_db),
) -> dict:
    asset = gis.get_asset(db, asset_id)
    code, name = asset.code, asset.name
    gis.soft_delete(db, asset, actor=user)
    audit.add(
        "asset.deleted",
        entity="asset",
        entity_id=asset_id,
        detail=f"Удалён объект {code} ({name})",
    )
    return {"message": "Объект удалён", "id": str(asset_id)}


@router.get(
    "/assets/{asset_id}/power-path",
    response_model=PowerPathOut,
    summary="Цепочка питания (предварительная)",
)
def asset_power_path(
    asset_id: uuid.UUID,
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> PowerPathOut:
    asset = gis.get_asset(db, asset_id)
    return gis.power_path(db, asset)


# --- карта -----------------------------------------------------------------

@router.get("/map/layers/active", response_model=MapLayerOut, summary="Активная подложка")
def active_layer(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> MapLayerOut:
    pit = gis.get_pit(db)
    layer = gis.get_active_layer(db, pit.id)
    if layer is None:
        raise not_found("Подложка карты не настроена")
    return gis.layer_out(layer)
