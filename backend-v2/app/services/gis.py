"""Логика ГИС-реестра: объекты, порты, координаты, путь питания."""

from __future__ import annotations

import math
import re

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError, conflict, not_found
from app.models import Asset, AssetPort, AssetType, Link, MapLayer, Pit
from app.schemas.gis import (
    AssetBriefOut,
    AssetCreate,
    AssetOut,
    AssetTypeCreate,
    AssetTypeFieldIn,
    AssetUpdate,
    FeederRefOut,
    MapLayerOut,
    PortOut,
    PowerPathNode,
    PowerPathOut,
    TypeRefOut,
)
from app.services import asset_fields

SYNTHETIC_SOURCE = {
    "code": "PS-356",
    "name": "ПС-35/6 кВ «Карьер»",
    "type_code": "substation",
    "type_name": "Подстанция 35/6 кВ",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


# --- карьер и подложка -----------------------------------------------------

def get_pit(db: Session) -> Pit:
    pit = db.scalar(select(Pit).where(Pit.is_active.is_(True)).order_by(Pit.created_at))
    if pit is None:
        raise ApiError(409, "gis.not_configured", "Карьер не настроен: выполните seed_gis.py")
    return pit


def get_active_layer(db: Session, pit_id: uuid.UUID) -> MapLayer | None:
    return db.scalar(
        select(MapLayer)
        .where(MapLayer.pit_id == pit_id, MapLayer.is_active.is_(True))
        .order_by(MapLayer.version.desc())
    )


def layer_size(layer: MapLayer) -> tuple[float, float]:
    mpp = float(layer.meters_per_pixel or 0.5)
    return layer.width_px * mpp, layer.height_px * mpp


def layer_out(layer: MapLayer) -> MapLayerOut:
    width_m, height_m = layer_size(layer)
    origin_x = float(layer.origin_x or 0)
    origin_y = float(layer.origin_y or 0)
    return MapLayerOut(
        id=layer.id,
        name=layer.name,
        image_url=layer.image_url,
        width_px=layer.width_px,
        height_px=layer.height_px,
        meters_per_pixel=float(layer.meters_per_pixel),
        width_m=width_m,
        height_m=height_m,
        # Leaflet CRS.Simple: [[y0, x0], [y1, x1]] в метрах с учётом начала координат
        bounds=[[origin_y, origin_x], [origin_y + height_m, origin_x + width_m]],
        min_zoom=layer.min_zoom,
        max_zoom=layer.max_zoom,
        version=layer.version,
    )


def create_map_layer(
    db: Session,
    pit_id: uuid.UUID,
    *,
    name: str,
    data: bytes,
    width_px: int,
    height_px: int,
    meters_per_pixel: float,
    origin_x: float,
    origin_y: float,
    actor: AssetType | None = None,
    actor_id: uuid.UUID | None = None,
) -> MapLayer:
    """Загрузить новую подложку: прежние слои деактивируются, координаты объектов не меняются."""
    from app.services.storage import storage

    if not (0.01 <= meters_per_pixel <= 20):
        raise ApiError(422, "map.bad_scale", "Масштаб должен быть от 0.01 до 20 м/пиксель")
    if width_px < 200 or height_px < 200:
        raise ApiError(422, "map.too_small", "Карта слишком маленькая (минимум 200×200 px)")

    layer_id = uuid.uuid4()
    key = f"maps/{layer_id}.png"
    storage.save(data, key=key)

    db.execute(
        update(MapLayer).where(MapLayer.pit_id == pit_id).values(is_active=False)
    )

    version = (
        db.scalar(select(func.max(MapLayer.version)).where(MapLayer.pit_id == pit_id)) or 0
    ) + 1

    layer = MapLayer(
        id=layer_id,
        pit_id=pit_id,
        name=name,
        kind="raster",
        image_url=f"/api/map/layers/{layer_id}/image",
        width_px=width_px,
        height_px=height_px,
        meters_per_pixel=meters_per_pixel,
        origin_x=origin_x,
        origin_y=origin_y,
        version=version,
        is_active=True,
        uploaded_by=actor_id,
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)

    from app.services import audit

    audit.add(
        "map.layer_uploaded",
        entity="map_layer",
        entity_id=layer.id,
        detail=f"Загружена карта «{name}»: {width_px}×{height_px} px, {meters_per_pixel} м/px",
        payload={"version": version, "width_px": width_px, "height_px": height_px},
    )
    return layer


# --- сериализация ----------------------------------------------------------

def type_ref(asset_type: AssetType) -> TypeRefOut:
    equipment_class = asset_fields.effective_class(asset_type)
    return TypeRefOut(
        code=asset_type.code,
        name=asset_type.name,
        category=asset_type.category,
        icon=asset_type.icon,
        color=asset_type.color,
        equipment_class=equipment_class,
        group_code=asset_type.group_code or asset_fields.group_for_class(equipment_class),
    )


def asset_brief(asset: Asset, feeders: list[FeederRefOut] | None = None) -> AssetBriefOut:
    return AssetBriefOut(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        type=type_ref(asset.asset_type),
        status=asset.status,
        is_mobile=asset.is_mobile,
        grounded=asset.grounded,
        x=float(asset.x) if asset.x is not None else None,
        y=float(asset.y) if asset.y is not None else None,
        location_text=asset.location_text,
        cell_kind=asset.cell_kind,
        cell_no=asset.cell_no,
        section_no=asset.section_no,
        lifecycle_status=asset.lifecycle_status,
        parent_id=asset.parent_asset_id,
        grouped=asset.schema_block_id is not None,
        feeders=list(feeders or []),
        version=asset.version,
        updated_at=asset.updated_at,
    )


def asset_full(asset: Asset, feeders: list[FeederRefOut] | None = None) -> AssetOut:
    return AssetOut(
        id=asset.id,
        pit_id=asset.pit_id,
        code=asset.code,
        name=asset.name,
        type=type_ref(asset.asset_type),
        status=asset.status,
        lifecycle=asset.lifecycle,
        grounded=asset.grounded,
        is_mobile=asset.is_mobile,
        x=float(asset.x) if asset.x is not None else None,
        y=float(asset.y) if asset.y is not None else None,
        z=float(asset.z) if asset.z is not None else None,
        lat=float(asset.lat) if asset.lat is not None else None,
        lon=float(asset.lon) if asset.lon is not None else None,
        schema_x=float(asset.schema_x) if asset.schema_x is not None else None,
        schema_y=float(asset.schema_y) if asset.schema_y is not None else None,
        schema_local_x=(
            float(asset.schema_local_x) if asset.schema_local_x is not None else None
        ),
        schema_local_y=(
            float(asset.schema_local_y) if asset.schema_local_y is not None else None
        ),
        schema_width=float(asset.schema_width) if asset.schema_width is not None else None,
        schema_height=float(asset.schema_height) if asset.schema_height is not None else None,
        location_text=asset.location_text,
        attrs=asset.attrs or {},
        cell_kind=asset.cell_kind,
        cell_no=asset.cell_no,
        section_no=asset.section_no,
        lifecycle_status=asset.lifecycle_status,
        parent_id=asset.parent_asset_id,
        parent_name=asset.parent.name if asset.parent else None,
        ports=[
            PortOut(
                id=p.id,
                code=p.code,
                name=p.name,
                kind=p.kind,
                nominal_voltage_kv=float(p.nominal_voltage_kv) if p.nominal_voltage_kv else None,
                sort_order=p.sort_order,
            )
            for p in asset.ports
        ],
        feeders=list(feeders or []),
        version=asset.version,
        updated_at=asset.updated_at,
    )


# --- выборки ---------------------------------------------------------------

def asset_query(pit_id: uuid.UUID):
    return (
        select(Asset)
        .where(Asset.pit_id == pit_id, Asset.deleted_at.is_(None))
        .options(selectinload(Asset.ports))
    )


def list_assets(
    db: Session,
    *,
    pit_id: uuid.UUID,
    q: str | None = None,
    type_code: str | None = None,
    status: str | None = None,
    is_mobile: bool | None = None,
    parent_id: uuid.UUID | None = None,
    feeder_ids: set[uuid.UUID] | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[Asset], int]:
    stmt = asset_query(pit_id)
    if feeder_ids is not None:
        # фильтр по фидеру: явный набор объектов линии (см. topology.feeder_asset_ids)
        if not feeder_ids:
            return [], 0
        stmt = stmt.where(Asset.id.in_(feeder_ids))
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Asset.name.ilike(needle), Asset.code.ilike(needle)))
    if type_code:
        stmt = stmt.join(AssetType, Asset.asset_type_id == AssetType.id).where(
            AssetType.code == type_code
        )
    if status:
        stmt = stmt.where(Asset.status == status)
    if is_mobile is not None:
        stmt = stmt.where(Asset.is_mobile.is_(is_mobile))
    if parent_id is not None:
        stmt = stmt.where(Asset.parent_asset_id == parent_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Asset.code).limit(limit).offset(offset)).unique().all()
    return list(rows), total


def get_asset(db: Session, asset_id: uuid.UUID, *, pit_id: uuid.UUID | None = None) -> Asset:
    asset = db.scalar(
        select(Asset)
        .where(Asset.id == asset_id, Asset.deleted_at.is_(None))
        .options(selectinload(Asset.ports))
    )
    if asset is None or (pit_id is not None and asset.pit_id != pit_id):
        raise not_found("Объект не найден")
    return asset


def get_type(db: Session, code: str) -> AssetType:
    asset_type = db.scalar(select(AssetType).where(AssetType.code == code, AssetType.is_active.is_(True)))
    if asset_type is None:
        raise ApiError(400, "asset.unknown_type", f"Неизвестный тип объекта: {code}")
    return asset_type


def list_types(db: Session, *, include_inactive: bool = False) -> list[AssetType]:
    stmt = select(AssetType).order_by(AssetType.sort_order, AssetType.name)
    if not include_inactive:
        stmt = stmt.where(AssetType.is_active.is_(True))
    return list(db.scalars(stmt).unique())


def type_out(db: Session, asset_type: AssetType, *, with_fields: bool = False) -> dict[str, Any]:
    """Тип для админки: с родителем и числом объектов.

    ``with_fields=True`` добавляет поля паспорта (динамическая форма реестра);
    по умолчанию их нет, чтобы старые клиенты не получали лишний payload.
    """
    assets_count = db.scalar(
        select(func.count(Asset.id)).where(
            Asset.asset_type_id == asset_type.id, Asset.deleted_at.is_(None)
        )
    ) or 0
    equipment_class = asset_fields.effective_class(asset_type)
    data: dict[str, Any] = {
        "id": asset_type.id,
        "code": asset_type.code,
        "name": asset_type.name,
        "category": asset_type.category,
        "equipment_class": equipment_class,
        "group_code": asset_type.group_code or asset_fields.group_for_class(equipment_class),
        "schema_symbol": asset_type.schema_symbol,
        "icon": asset_type.icon,
        "color": asset_type.color,
        "port_template": asset_type.port_template or {},
        "attr_schema": asset_type.attr_schema or {},
        "required_attrs": list(asset_type.required_attrs or []),
        "is_mobile_default": asset_type.is_mobile_default,
        "has_maintenance": asset_type.has_maintenance,
        "is_composite": asset_type.is_composite,
        "composite_template": asset_type.composite_template or [],
        "sort_order": asset_type.sort_order,
        "is_active": asset_type.is_active,
        "description": asset_type.description,
        "parent_id": asset_type.parent_id,
        "parent_name": asset_type.parent.name if asset_type.parent else None,
        "assets_count": int(assets_count),
    }
    if with_fields:
        data["fields"] = asset_fields.public_fields(asset_type)
    return data


# --- валидация -------------------------------------------------------------

def validate_attrs(
    asset_type: AssetType, attrs: dict[str, Any], *, check_required: bool = True
) -> dict[str, str]:
    """Legacy-проверка по required_attrs/attr_schema (совместимость).

    Основной путь этапа 1 — :func:`app.services.asset_fields.validate_asset_fields`
    (поля gis.asset_type_fields). Функция оставлена для внешнего кода и как
    аварийный путь, если таблица полей недоступна.
    """
    errors, _labels = asset_fields.validate_asset_fields(
        asset_type, attrs, check_required=check_required
    )
    return errors


def check_bounds(db: Session, pit_id: uuid.UUID, x: float | None, y: float | None) -> None:
    if x is None or y is None:
        return
    layer = get_active_layer(db, pit_id)
    if layer is None:
        return
    width_m, height_m = layer_size(layer)
    if not (0 <= x <= width_m and 0 <= y <= height_m):
        raise ApiError(
            422,
            "asset.out_of_bounds",
            f"Координаты вне карты: допустимо X 0…{width_m:.0f} м, Y 0…{height_m:.0f} м",
            fields={"x": f"0…{width_m:.0f}", "y": f"0…{height_m:.0f}"},
        )


# --- изменение -------------------------------------------------------------

def generate_code(db: Session, pit_id: uuid.UUID, asset_type: AssetType) -> str:
    prefix = asset_type.code.upper()
    existing = db.scalars(
        select(Asset.code).where(Asset.pit_id == pit_id, Asset.code.ilike(f"{prefix}-%"))
    ).all()
    numbers = []
    for code in existing:
        tail = code.split("-", 1)[-1]
        if tail.isdigit():
            numbers.append(int(tail))
    next_number = (max(numbers) + 1) if numbers else 1
    return f"{prefix}-{next_number}"


def create_ports(db: Session, asset: Asset, asset_type: AssetType) -> None:
    template = asset_type.port_template or {}
    ports = template.get("ports") or []
    for index, port in enumerate(ports):
        db.add(
            AssetPort(
                id=uuid.uuid4(),
                asset_id=asset.id,
                code=port.get("code", f"P-{index + 1}"),
                name=port.get("name", "Порт"),
                kind=port.get("kind", "in"),
                nominal_voltage_kv=port.get("voltage_kv"),
                sort_order=port.get("sort_order", index),
            )
        )


def create_asset(
    db: Session,
    payload: AssetCreate,
    *,
    actor,
    validate_attributes: bool = True,
    commit: bool = True,
) -> Asset:
    """Создать объект реестра вместе с портами типа.

    ``commit=False`` — для составных операций (блок + ячейки одним вызовом
    ``POST /api/schema/composite``): строки только ``flush``-ятся, фиксирует их
    вызывающий код одной транзакцией. Поведение по умолчанию не изменилось.
    """
    pit = get_pit(db)
    asset_type = get_type(db, payload.type_code)

    # Для ячеек схемы (дочерних объектов блока) атрибуты типа не обязательны:
    # ячейка — визуальный элемент, её электрические параметры заполняются позже
    # в карточке. Иначе тип-аналог с required_attrs ломает создание пачки ячеек.
    if validate_attributes:
        errors, labels = asset_fields.validate_asset_fields(asset_type, payload.attrs)
        if errors:
            raise ApiError(
                422,
                "validation.failed",
                asset_fields.validation_detail(labels, errors),
                fields=errors,
                field_labels=labels,
            )
    check_bounds(db, pit.id, payload.x, payload.y)

    code = (payload.code or "").strip() or generate_code(db, pit.id, asset_type)
    duplicate = db.scalar(
        select(Asset).where(Asset.pit_id == pit.id, Asset.code == code, Asset.deleted_at.is_(None))
    )
    if duplicate is not None:
        raise conflict(f"Объект с кодом {code} уже существует", "asset.duplicate_code")

    parent_id = payload.parent_id
    if parent_id is not None:
        parent = db.scalar(select(Asset).where(Asset.id == parent_id, Asset.deleted_at.is_(None)))
        if parent is None:
            raise ApiError(400, "asset.parent_not_found", "Родительский объект не найден")

    asset = Asset(
        id=uuid.uuid4(),
        pit_id=pit.id,
        asset_type_id=asset_type.id,
        parent_asset_id=parent_id,
        code=code,
        name=payload.name,
        location_text=payload.location_text,
        status=payload.status,
        lifecycle=payload.lifecycle,
        is_mobile=asset_type.is_mobile_default if payload.is_mobile is None else payload.is_mobile,
        x=payload.x,
        y=payload.y,
        z=payload.z,
        lat=payload.lat,
        lon=payload.lon,
        attrs=payload.attrs or {},
        cell_kind=payload.cell_kind,
        cell_no=payload.cell_no,
        section_no=payload.section_no,
        lifecycle_status=payload.lifecycle_status
        or ("installed" if asset_fields.effective_class(asset_type) == "cable" else None),
        created_by=actor.id,
        updated_by=actor.id,
        version=1,
    )
    db.add(asset)
    db.flush()
    create_ports(db, asset, asset_type)
    if not commit:
        db.flush()
        return asset
    db.commit()
    db.refresh(asset)
    return get_asset(db, asset.id)


def update_asset(db: Session, asset: Asset, payload: AssetUpdate, *, actor) -> Asset:
    if payload.expected_version is not None and payload.expected_version != asset.version:
        raise conflict(
            f"Объект изменён другим пользователем (версия {asset.version})", "conflict.version"
        )

    data = payload.model_dump(exclude_unset=True)
    data.pop("expected_version", None)

    if "x" in data or "y" in data:
        check_bounds(
            db,
            asset.pit_id,
            data.get("x", float(asset.x) if asset.x is not None else None),
            data.get("y", float(asset.y) if asset.y is not None else None),
        )

    if "attrs" in data and data["attrs"] is not None:
        errors, labels = asset_fields.validate_asset_fields(
            asset.asset_type, data["attrs"], check_required=asset.schema_block_id is None
        )
        if errors:
            raise ApiError(
                422,
                "validation.failed",
                asset_fields.validation_detail(labels, errors),
                fields=errors,
                field_labels=labels,
            )
        asset.attrs = data.pop("attrs")

    if "parent_id" in data:
        parent_id = data.pop("parent_id")
        if parent_id is not None:
            if parent_id == asset.id:
                raise ApiError(400, "asset.parent_cycle", "Объект не может быть родителем сам себе")
            parent = db.scalar(select(Asset).where(Asset.id == parent_id, Asset.deleted_at.is_(None)))
            if parent is None:
                raise ApiError(400, "asset.parent_not_found", "Родительский объект не найден")
        asset.parent_asset_id = parent_id

    if "code" in data and data["code"]:
        duplicate = db.scalar(
            select(Asset).where(
                Asset.pit_id == asset.pit_id,
                Asset.code == data["code"],
                Asset.id != asset.id,
                Asset.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise conflict(f"Объект с кодом {data['code']} уже существует", "asset.duplicate_code")

    for field, value in data.items():
        setattr(asset, field, value)

    asset.updated_by = actor.id
    asset.version = (asset.version or 1) + 1
    db.commit()
    return get_asset(db, asset.id)


def soft_delete(db: Session, asset: Asset, *, actor) -> None:
    timestamp = now()
    asset.deleted_at = timestamp
    asset.deleted_by = actor.id
    asset.version = (asset.version or 1) + 1

    # Связи, висящие на портах удаляемого объекта, тоже уходят в архив. Иначе они
    # остаются «живыми» (deleted_at IS NULL): торчат в /api/links без второго конца,
    # занимают уникальную пару портов и всплывают, если объект вернут из архива.
    port_ids = [port.id for port in asset.ports]
    if port_ids:
        stale_links = db.scalars(
            select(Link).where(
                Link.deleted_at.is_(None),
                or_(Link.from_port_id.in_(port_ids), Link.to_port_id.in_(port_ids)),
            )
        ).all()
        for link in stale_links:
            link.deleted_at = timestamp
            link.deleted_by = actor.id
            link.version = (link.version or 1) + 1

    db.commit()


def get_archived_asset(db: Session, asset_id: uuid.UUID) -> Asset:
    """Объект из архива (deleted_at NOT NULL) — для отмены удаления."""
    asset = db.scalar(
        select(Asset)
        .where(Asset.id == asset_id, Asset.deleted_at.is_not(None))
        .options(selectinload(Asset.ports))
    )
    if asset is None:
        raise not_found("Объект не найден в архиве")
    return asset


def restore_asset(db: Session, asset: Asset, *, actor) -> None:
    """Вернуть объект из архива вместе со связями, ушедшими вместе с ним.

    Связь восстанавливается, только если её второй конец жив: иначе в графе
    появился бы висячий участок к архивному объекту. По той же причине нельзя
    вернуть объект, чей родитель (блок, группа, контейнер) остался в архиве:
    иначе в реестре появится иерархия со ссылкой на несуществующий узел.
    """
    if asset.parent_asset_id is not None:
        parent = db.get(Asset, asset.parent_asset_id)
        if parent is not None and parent.deleted_at is not None:
            raise conflict(
                "Родительский объект находится в архиве — сначала верните его",
                "asset.parent_archived",
            )

    archived_at = asset.deleted_at
    asset.deleted_at = None
    asset.deleted_by = None
    asset.version = (asset.version or 1) + 1

    port_ids = [port.id for port in asset.ports]
    if port_ids and archived_at is not None:
        links = db.scalars(
            select(Link).where(
                Link.deleted_at == archived_at,
                or_(Link.from_port_id.in_(port_ids), Link.to_port_id.in_(port_ids)),
            )
        ).all()
        for link in links:
            from_port = db.get(AssetPort, link.from_port_id)
            to_port = db.get(AssetPort, link.to_port_id)
            endpoints = [
                db.get(Asset, port.asset_id) if port is not None else None
                for port in (from_port, to_port)
            ]
            if any(endpoint is None or endpoint.deleted_at is not None for endpoint in endpoints):
                continue
            link.deleted_at = None
            link.deleted_by = None
            link.version = (link.version or 1) + 1

    db.commit()


# --- путь питания (Спринт 2: по вложенности, до связей Спринта 3) -----------

def power_path(db: Session, asset: Asset) -> PowerPathOut:
    chain: list[Asset] = []
    visited: set[uuid.UUID] = set()
    current: Asset | None = asset
    depth = 0

    while current is not None and depth < 32:
        if current.id in visited:
            break
        visited.add(current.id)
        chain.append(current)
        current = current.parent
        depth += 1

    chain.reverse()  # от источника к объекту

    nodes: list[PowerPathNode] = []
    top = chain[0] if chain else None
    if top is not None and top.asset_type and top.asset_type.category == "source":
        source = PowerPathNode(
            id=top.id,
            code=top.code,
            name=top.name,
            type_code=top.asset_type.code,
            type_name=top.asset_type.name,
            role="source",
        )
        rest = chain[1:]
    else:
        source = PowerPathNode(
            code=SYNTHETIC_SOURCE["code"],
            name=SYNTHETIC_SOURCE["name"],
            type_code=SYNTHETIC_SOURCE["type_code"],
            type_name=SYNTHETIC_SOURCE["type_name"],
            role="source",
            synthetic=True,
        )
        rest = chain

    for index, node in enumerate(rest):
        is_last = index == len(rest) - 1
        nodes.append(
            PowerPathNode(
                id=node.id,
                code=node.code,
                name=node.name,
                type_code=node.asset_type.code if node.asset_type else None,
                type_name=node.asset_type.name if node.asset_type else None,
                role="asset" if is_last else "feed",
            )
        )

    return PowerPathOut(
        asset_id=asset.id,
        asset_name=asset.name,
        source=source,
        chain=nodes,
        note=(
            "Предварительная цепочка по вложенности объектов. "
            "Полный расчёт по графу связей — Спринт 3."
        ),
    )


# --- типы объектов (админка) ----------------------------------------------

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slug_from_name(name: str) -> str:
    """Транслит названия в код типа: «ПС 35/6 кВ» → ps_35_6_kv."""
    lower = name.strip().lower()
    transliterated = "".join(TRANSLIT.get(char, char) for char in lower)
    cleaned = re.sub(r"[^a-z0-9]+", "_", transliterated).strip("_")
    if not cleaned:
        cleaned = "type"
    if not cleaned[0].isalpha():
        cleaned = f"t_{cleaned}"
    return cleaned[:48]


def unique_type_code(db: Session, base: str) -> str:
    candidate = base
    index = 2
    while db.scalar(select(AssetType).where(AssetType.code == candidate)) is not None:
        suffix = f"_{index}"
        candidate = f"{base[: 48 - len(suffix)]}{suffix}"
        index += 1
    return candidate


def create_type(db: Session, payload: AssetTypeCreate) -> AssetType:
    code = (payload.code or "").strip().lower()
    if code:
        if db.scalar(select(AssetType).where(AssetType.code == code)) is not None:
            raise conflict(f"Тип {code} уже существует", "asset_type.duplicate_code")
    else:
        code = unique_type_code(db, slug_from_name(payload.name))
    if payload.parent_id is not None:
        parent = db.get(AssetType, payload.parent_id)
        if parent is None:
            raise ApiError(400, "asset_type.parent_not_found", "Родительский тип не найден")
    equipment_class = payload.equipment_class or asset_fields.infer_equipment_class(
        code, payload.name, payload.category
    )
    asset_type = AssetType(
        id=uuid.uuid4(),
        code=code,
        name=payload.name,
        category=payload.category,
        equipment_class=equipment_class,
        group_code=payload.group_code or asset_fields.group_for_class(equipment_class),
        schema_symbol=payload.schema_symbol or "load",
        icon=payload.icon or "●",
        color=payload.color or "#4C9AFF",
        port_template=payload.port_template or {"ports": []},
        attr_schema=payload.attr_schema or {},
        required_attrs=payload.required_attrs or [],
        is_mobile_default=payload.is_mobile_default,
        has_maintenance=payload.has_maintenance,
        is_composite=payload.is_composite,
        composite_template=payload.composite_template or [],
        sort_order=payload.sort_order,
        description=payload.description,
        parent_id=payload.parent_id,
        is_active=True,
    )
    db.add(asset_type)
    db.flush()
    if payload.fields:
        # Админ задал поля конструктором: они источник правды, legacy-схема
        # пересобирается из них (двойная запись для старых клиентов).
        asset_fields.replace_fields(db, asset_type, payload.fields)
    else:
        asset_fields.sync_from_schema(db, asset_type)
    if payload.parent_id is not None:
        parent = db.get(AssetType, payload.parent_id)
        if parent is not None:
            sync_composite_template(db, parent)
    db.commit()
    db.refresh(asset_type)
    return asset_type


def _descendants(db: Session, asset_type: AssetType) -> set[uuid.UUID]:
    """Все потомки типа — чтобы не создать цикл в дереве."""
    found: set[uuid.UUID] = set()
    stack = [asset_type.id]
    while stack:
        current = stack.pop()
        children = db.scalars(
            select(AssetType).where(AssetType.parent_id == current)
        ).all()
        for child in children:
            if child.id not in found:
                found.add(child.id)
                stack.append(child.id)
    return found


def sync_composite_template(db: Session, parent: AssetType) -> None:
    """Если у типа есть подтипы — он комплектный; недостающие подтипы попадают в состав."""
    children = list(
        db.scalars(select(AssetType).where(AssetType.parent_id == parent.id, AssetType.is_active.is_(True))).all()
    )
    if not children:
        return
    parent.is_composite = True
    template = list(parent.composite_template or [])
    known = {str(item.get("type_code")) for item in template if isinstance(item, dict)}
    for child in children:
        if child.code not in known:
            template.append({"type_code": child.code, "count": 1, "label": child.name})
    parent.composite_template = template


def update_type(db: Session, asset_type: AssetType, data: Any) -> AssetType:
    payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)

    parent_marker = payload.pop("clear_parent", False)
    if "parent_id" in payload:
        parent_id = payload.pop("parent_id")
        if parent_id is not None and parent_id == asset_type.id:
            raise ApiError(400, "asset_type.parent_cycle", "Тип не может быть родителем сам себе")
        if parent_id is not None and parent_id in _descendants(db, asset_type):
            raise ApiError(400, "asset_type.parent_cycle", "Нельзя вложить тип в собственный подтип")
        if parent_id is not None and db.get(AssetType, parent_id) is None:
            raise ApiError(400, "asset_type.parent_not_found", "Родительский тип не найден")
        asset_type.parent_id = parent_id
    elif parent_marker:
        asset_type.parent_id = None

    # поля конструктора: если переданы — они источник правды для attr_schema
    fields_payload = payload.pop("fields", None)
    fields_changed = fields_payload is not None

    if payload.get("equipment_class"):
        equipment_class = payload.pop("equipment_class")
        changed = equipment_class != asset_type.equipment_class
        asset_type.equipment_class = equipment_class
        if changed and "group_code" not in payload:
            asset_type.group_code = asset_fields.group_for_class(equipment_class)
    if "group_code" in payload:
        asset_type.group_code = payload.pop("group_code")

    for field in (
        "name",
        "category",
        "schema_symbol",
        "icon",
        "color",
        "port_template",
        "attr_schema",
        "required_attrs",
        "is_mobile_default",
        "has_maintenance",
        "is_composite",
        "composite_template",
        "sort_order",
        "description",
        "is_active",
    ):
        if field in payload and payload[field] is not None:
            setattr(asset_type, field, payload[field])

    if fields_changed:
        asset_fields.replace_fields(
            db,
            asset_type,
            [AssetTypeFieldIn(**item) if isinstance(item, dict) else item for item in fields_payload],
        )
    elif "attr_schema" in payload or "required_attrs" in payload:
        asset_fields.sync_from_schema(db, asset_type)

    sync_composite_template(db, asset_type)
    db.commit()
    db.refresh(asset_type)
    return asset_type


def deactivate_type(db: Session, asset_type: AssetType) -> None:
    """Мягкое удаление типа: запрещено, если он используется или имеет подтипы."""
    used = db.scalar(
        select(func.count(Asset.id)).where(
            Asset.asset_type_id == asset_type.id, Asset.deleted_at.is_(None)
        )
    ) or 0
    if used:
        raise conflict(
            f"Тип используется объектами: {used}. Сначала переназначьте их",
            "asset_type.in_use",
        )
    children = db.scalar(
        select(func.count(AssetType.id)).where(
            AssetType.parent_id == asset_type.id, AssetType.is_active.is_(True)
        )
    ) or 0
    if children:
        raise conflict(
            f"У типа есть подтипы: {children}. Сначала удалите или перенесите их",
            "asset_type.has_children",
        )
    asset_type.is_active = False
    db.commit()


# --- раскладка схемы (этап 3: автосейв, размеры блоков, координаты ячеек) ----

#: Минимальный размер блока на схеме, px. Меньше — NodeResizer и подписи блока
#: перестают помещаться; больше ``MAX_SCHEMA_BLOCK_SIZE`` — почти наверняка
#: опечатка или ошибка клиента, а не реальный ресайз.
MIN_SCHEMA_BLOCK_WIDTH = 120.0
MIN_SCHEMA_BLOCK_HEIGHT = 80.0
MAX_SCHEMA_BLOCK_SIZE = 10_000.0


def is_schema_block(asset: Asset) -> bool:
    """Блок схемы — корневой объект с ``block_code`` или ролью ``block``.

    Та же логика, что ``schema_blocks.is_container`` (ПС/БКРУ/КТП/контур), но
    без импорта сервиса блоков: он сам импортирует этот модуль (цикл).
    """
    if asset.schema_block_id is not None:
        return False
    return asset.schema_role == "block" or bool((asset.attrs or {}).get("block_code"))


def block_size(asset: Asset) -> tuple[float | None, float | None]:
    """Размер блока: колонки этапа 3, иначе старые ``attrs.contour_w/contour_h``.

    Fallback нужен и после миграции: объекты, созданные старым кодом/импортом,
    могут не иметь новых колонок, пока их не пересохранили.
    """
    attrs = asset.attrs or {}
    width = asset.schema_width
    height = asset.schema_height
    if width is None:
        width = attrs.get("contour_w")
    if height is None:
        height = attrs.get("contour_h")
    try:
        width_value = float(width) if width is not None else None
    except (TypeError, ValueError):
        width_value = None
    try:
        height_value = float(height) if height is not None else None
    except (TypeError, ValueError):
        height_value = None
    return width_value, height_value


def _layout_number(value: Any, *, field: str, label: str) -> float:
    """Привести координату/размер к конечному числу или отказать 422."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(
            422,
            "layout.invalid_number",
            f"{label} ({field}): ожидается число",
            fields={field: "ожидается число"},
        ) from None
    if not math.isfinite(number):
        raise ApiError(
            422,
            "layout.invalid_number",
            f"{label} ({field}): ожидается конечное число",
            fields={field: "ожидается конечное число"},
        )
    return number


def _check_cell_bound(
    *,
    asset: Asset,
    parent: Asset | None,
    value: float,
    limit: float | None,
    axis: str,
    field: str,
    current: float | None = None,
) -> None:
    """Ячейка должна лежать внутри прямоугольника своего блока (0…width/height).

    Исключение — «уже сохранённое» значение (``current``): старые раскладки
    этапа 2 ставили ячейки шире клиентского дефолта блока, и автосейв, который
    присылает состояние целиком, не должен вечно получать 422 за координаты,
    которые сервер сам же и записал. Валидируются именно **изменения**: новое
    вне-граничное значение отклоняется, неизменное — принимается как есть.
    """
    if current is not None and abs(current - value) <= 1e-6:
        return
    if value < 0:
        block_name = parent.name if parent is not None else "блок"
        raise ApiError(
            422,
            "layout.out_of_bounds",
            f"Ячейка {asset.code}: {axis} {value:g} px отрицательная — "
            f"координаты внутри блока «{block_name}» начинаются с 0",
            fields={field: "0…ширина/высота блока"},
        )
    if limit is None:
        return
    if value > limit:
        block_name = parent.name if parent is not None else "блок"
        raise ApiError(
            422,
            "layout.out_of_bounds",
            f"Ячейка {asset.code}: {axis} {value:g} px выходит за границы блока "
            f"«{block_name}» (допустимо 0…{limit:g} px)",
            fields={field: f"0…{limit:g}"},
        )


def set_schema_layout(
    db: Session,
    pit_id: uuid.UUID,
    items: list[dict[str, float]],
    actor: Any,
    ports: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Сохранить ручную раскладку схемы точечными UPDATE.

    Этап 3: помимо абсолютных координат узла (``x``/``y``) принимает размер блока
    (``width``/``height``) и координаты ячейки внутри блока (``local_x``/
    ``local_y`` — существующие колонки ``gis.assets.schema_local_x/y``).

    Запрос вызывается автосейвом каждые ~2 с, поэтому:
      * объекты читаются одним запросом по списку id, а не «весь граф»;
      * UPDATE идут только по изменившимся строкам (SQLAlchemy dirty tracking),
        версии/``updated_at`` нетронутых объектов не меняются;
      * валидация выполняется ДО первой записи: частично некорректный payload
        отклоняется целиком (422) и раскладка остаётся прежней.
    """
    requested = [dict(item) for item in items]
    port_items = [dict(item) for item in (ports or [])]

    assets: dict[uuid.UUID, Asset] = {}
    asset_ids = {item["asset_id"] for item in requested}
    if asset_ids:
        rows = db.scalars(
            select(Asset).where(
                Asset.id.in_(asset_ids),
                Asset.pit_id == pit_id,
                Asset.deleted_at.is_(None),
            )
        ).unique().all()
        assets = {row.id: row for row in rows}

    # Родители ячеек — одним запросом: нужны границы блока для валидации.
    # Родитель может быть в другом карьере/архиве — тогда просто нет границ.
    parent_ids = {
        asset.schema_block_id
        for asset in assets.values()
        if asset.schema_block_id is not None and asset.schema_block_id not in assets
    }
    parents: dict[uuid.UUID, Asset] = {}
    if parent_ids:
        rows = db.scalars(
            select(Asset).where(
                Asset.id.in_(parent_ids),
                Asset.pit_id == pit_id,
                Asset.deleted_at.is_(None),
            )
        ).unique().all()
        parents = {row.id: row for row in rows}
    blocks_by_id: dict[uuid.UUID, Asset] = {**parents, **assets}

    # Размеры блоков: сперва из БД, затем накладываем новые размеры из payload —
    # тогда в одном запросе можно и увеличить блок, и подвинуть его ячейки.
    sizes: dict[uuid.UUID, tuple[float | None, float | None]] = {
        block_id: block_size(asset) for block_id, asset in blocks_by_id.items()
    }
    for item in requested:
        asset = assets.get(item["asset_id"])
        if asset is None or not is_schema_block(asset):
            continue
        width = item.get("width")
        height = item.get("height")
        if width is None and height is None:
            continue
        current_width, current_height = sizes.get(asset.id, (None, None))
        sizes[asset.id] = (
            float(width) if width is not None else current_width,
            float(height) if height is not None else current_height,
        )

    # --- валидация (ничего не пишем, пока не проверено всё) ------------------
    plan: list[tuple[Asset, dict[str, Any], str]] = []
    skipped: list[uuid.UUID] = []
    for item in requested:
        asset = assets.get(item["asset_id"])
        if asset is None:
            skipped.append(item["asset_id"])
            continue

        is_block = is_schema_block(asset)
        values: dict[str, Any] = {}
        kind = "node"

        x, y = item.get("x"), item.get("y")
        if x is not None:
            values["schema_x"] = _layout_number(x, field="x", label=f"Объект {asset.code}")
        if y is not None:
            values["schema_y"] = _layout_number(y, field="y", label=f"Объект {asset.code}")

        width, height = item.get("width"), item.get("height")
        if width is not None or height is not None:
            if not is_block:
                raise ApiError(
                    422,
                    "layout.not_block",
                    f"Объект {asset.code}: размер задаётся только для блока схемы "
                    "(ПС/БКРУ/КТП/контур)",
                    fields={"width": "только для блока", "height": "только для блока"},
                )
            if width is not None:
                width_value = _layout_number(
                    width, field="width", label=f"Блок {asset.code}"
                )
                if width_value < MIN_SCHEMA_BLOCK_WIDTH:
                    raise ApiError(
                        422,
                        "layout.size_too_small",
                        f"Блок {asset.code}: ширина {width_value:g} px меньше минимума "
                        f"{MIN_SCHEMA_BLOCK_WIDTH:g} px",
                        fields={"width": f"не меньше {MIN_SCHEMA_BLOCK_WIDTH:g}"},
                    )
                if width_value > MAX_SCHEMA_BLOCK_SIZE:
                    raise ApiError(
                        422,
                        "layout.size_too_large",
                        f"Блок {asset.code}: ширина {width_value:g} px больше предела "
                        f"{MAX_SCHEMA_BLOCK_SIZE:g} px",
                        fields={"width": f"не больше {MAX_SCHEMA_BLOCK_SIZE:g}"},
                    )
                values["schema_width"] = width_value
            if height is not None:
                height_value = _layout_number(
                    height, field="height", label=f"Блок {asset.code}"
                )
                if height_value < MIN_SCHEMA_BLOCK_HEIGHT:
                    raise ApiError(
                        422,
                        "layout.size_too_small",
                        f"Блок {asset.code}: высота {height_value:g} px меньше минимума "
                        f"{MIN_SCHEMA_BLOCK_HEIGHT:g} px",
                        fields={"height": f"не меньше {MIN_SCHEMA_BLOCK_HEIGHT:g}"},
                    )
                if height_value > MAX_SCHEMA_BLOCK_SIZE:
                    raise ApiError(
                        422,
                        "layout.size_too_large",
                        f"Блок {asset.code}: высота {height_value:g} px больше предела "
                        f"{MAX_SCHEMA_BLOCK_SIZE:g} px",
                        fields={"height": f"не больше {MAX_SCHEMA_BLOCK_SIZE:g}"},
                    )
                values["schema_height"] = height_value
            kind = "block"

        local_x, local_y = item.get("local_x"), item.get("local_y")
        if local_x is not None or local_y is not None:
            if is_block:
                raise ApiError(
                    422,
                    "layout.not_cell",
                    f"Объект {asset.code}: локальные координаты задаются только для "
                    "ячейки внутри блока — у самого блока есть только x/y",
                    fields={
                        "local_x": "только для ячейки",
                        "local_y": "только для ячейки",
                    },
                )
            parent = (
                blocks_by_id.get(asset.schema_block_id)
                if asset.schema_block_id is not None
                else None
            )
            block_width, block_height = (
                sizes.get(parent.id, (None, None)) if parent is not None else (None, None)
            )
            if local_x is not None:
                local_x_value = _layout_number(
                    local_x, field="local_x", label=f"Ячейка {asset.code}"
                )
                _check_cell_bound(
                    asset=asset,
                    parent=parent,
                    value=local_x_value,
                    limit=block_width,
                    axis="X",
                    field="local_x",
                    current=(
                        float(asset.schema_local_x)
                        if asset.schema_local_x is not None
                        else None
                    ),
                )
                values["schema_local_x"] = local_x_value
            if local_y is not None:
                local_y_value = _layout_number(
                    local_y, field="local_y", label=f"Ячейка {asset.code}"
                )
                _check_cell_bound(
                    asset=asset,
                    parent=parent,
                    value=local_y_value,
                    limit=block_height,
                    axis="Y",
                    field="local_y",
                    current=(
                        float(asset.schema_local_y)
                        if asset.schema_local_y is not None
                        else None
                    ),
                )
                values["schema_local_y"] = local_y_value
            if kind != "block":
                kind = "cell"

        if values:
            plan.append((asset, values, kind))

    # --- порты: старый контракт (доли 0…1), неизвестные — молча пропускаем ---
    wanted_port_ids = {item["port_id"] for item in port_items}
    port_map: dict[uuid.UUID, AssetPort] = {}
    if wanted_port_ids:
        rows = db.scalars(
            select(AssetPort)
            .join(Asset, AssetPort.asset_id == Asset.id)
            .where(
                AssetPort.id.in_(wanted_port_ids),
                Asset.pit_id == pit_id,
                Asset.deleted_at.is_(None),
            )
        ).unique().all()
        port_map = {row.id: row for row in rows}

    updated_ports = 0
    for item in port_items:
        port = port_map.get(item["port_id"])
        if port is None:
            continue
        port.schema_x = max(0.0, min(1.0, float(item["x"])))
        port.schema_y = max(0.0, min(1.0, float(item["y"])))
        updated_ports += 1

    if not plan and updated_ports == 0:
        # Нечего сохранять: не открываем транзакцию записи вовсе.
        return {
            "updated": 0,
            "updated_ports": 0,
            "updated_blocks": 0,
            "updated_cells": 0,
            "skipped": skipped,
        }

    # --- запись: только затронутые строки --------------------------------
    updated_blocks = updated_cells = 0
    for asset, values, kind in plan:
        for field, value in values.items():
            setattr(asset, field, value)
        if kind == "block":
            updated_blocks += 1
        elif kind == "cell":
            updated_cells += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    updated = len(plan)
    from app.services import audit

    audit.add(
        "schema.layout_saved",
        entity="pit",
        entity_id=pit_id,
        detail=(
            f"Сохранена ручная раскладка схемы: узлов {updated}, "
            f"портов {updated_ports} (блоков {updated_blocks}, ячеек {updated_cells})"
        ),
        payload={
            "updated": updated,
            "updated_ports": updated_ports,
            "updated_blocks": updated_blocks,
            "updated_cells": updated_cells,
            "skipped": [str(x) for x in skipped],
        },
    )
    return {
        "updated": updated,
        "updated_ports": updated_ports,
        "updated_blocks": updated_blocks,
        "updated_cells": updated_cells,
        "skipped": skipped,
    }


def request_meta(request: Request) -> dict[str, str]:
    return {"ip": request.client.host if request.client else "unknown"}

# --- рамка и штамп схемы ---------------------------------------------------

def get_schema_frame(db: Session, pit: Pit) -> dict:
    from app.schemas.gis import SchemaFrameOut

    frame = SchemaFrameOut(**(pit.schema_frame or {}))
    return frame.model_dump()


def save_schema_frame(db: Session, pit: Pit, data: dict) -> dict:
    from app.schemas.gis import SchemaFrameOut

    frame = SchemaFrameOut(**data)
    pit.schema_frame = frame.model_dump()
    db.commit()
    return frame.model_dump()