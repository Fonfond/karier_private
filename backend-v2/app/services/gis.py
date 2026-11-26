"""Логика ГИС-реестра: объекты, порты, координаты, путь питания."""

from __future__ import annotations

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
    AssetUpdate,
    FeederRefOut,
    MapLayerOut,
    PortOut,
    PowerPathNode,
    PowerPathOut,
    TypeRefOut,
)

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
    return TypeRefOut(
        code=asset_type.code,
        name=asset_type.name,
        category=asset_type.category,
        icon=asset_type.icon,
        color=asset_type.color,
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
        location_text=asset.location_text,
        attrs=asset.attrs or {},
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


def type_out(db: Session, asset_type: AssetType) -> dict[str, Any]:
    """Тип для админки: с родителем и числом объектов."""
    assets_count = db.scalar(
        select(func.count(Asset.id)).where(
            Asset.asset_type_id == asset_type.id, Asset.deleted_at.is_(None)
        )
    ) or 0
    return {
        "id": asset_type.id,
        "code": asset_type.code,
        "name": asset_type.name,
        "category": asset_type.category,
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


# --- валидация -------------------------------------------------------------

def validate_attrs(asset_type: AssetType, attrs: dict[str, Any]) -> dict[str, str]:
    """Проверить атрибуты по required_attrs и типам из attr_schema."""
    errors: dict[str, str] = {}
    schema = asset_type.attr_schema or {}
    for field in asset_type.required_attrs or []:
        if attrs.get(field) in (None, ""):
            errors[field] = "Обязательное поле"

    for field, value in attrs.items():
        rule = schema.get(field)
        if not rule or value in (None, ""):
            continue
        expected = rule.get("type")
        if expected == "number" and not isinstance(value, (int, float)):
            errors[field] = "Ожидается число"
        elif expected == "integer" and not isinstance(value, int):
            errors[field] = "Ожидается целое число"
        elif expected == "boolean" and not isinstance(value, bool):
            errors[field] = "Ожидается да/нет"
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


def create_asset(db: Session, payload: AssetCreate, *, actor) -> Asset:
    pit = get_pit(db)
    asset_type = get_type(db, payload.type_code)

    errors = validate_attrs(asset_type, payload.attrs)
    if errors:
        raise ApiError(422, "validation.failed", "Проверьте атрибуты объекта", fields=errors)
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
        created_by=actor.id,
        updated_by=actor.id,
        version=1,
    )
    db.add(asset)
    db.flush()
    create_ports(db, asset, asset_type)
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
        errors = validate_attrs(asset.asset_type, data["attrs"])
        if errors:
            raise ApiError(422, "validation.failed", "Проверьте атрибуты объекта", fields=errors)
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
    asset_type = AssetType(
        id=uuid.uuid4(),
        code=code,
        name=payload.name,
        category=payload.category,
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


def set_schema_layout(
    db: Session,
    pit_id: uuid.UUID,
    items: list[dict[str, float]],
    actor: Any,
    ports: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Сохранить ручные координаты узлов и позиции портов однолинейной схемы."""
    updated = 0
    skipped: list[uuid.UUID] = []
    for item in items:
        asset = db.scalar(
            select(Asset).where(
                Asset.id == item["asset_id"], Asset.pit_id == pit_id, Asset.deleted_at.is_(None)
            )
        )
        if asset is None:
            skipped.append(item["asset_id"])
            continue
        asset.schema_x = item["x"]
        asset.schema_y = item["y"]
        updated += 1

    updated_ports = 0
    for item in ports or []:
        port = db.get(AssetPort, item["port_id"])
        if port is None or port.asset is None or port.asset.pit_id != pit_id:
            continue
        port.schema_x = max(0.0, min(1.0, float(item["x"])))
        port.schema_y = max(0.0, min(1.0, float(item["y"])))
        updated_ports += 1

    db.commit()
    if updated or updated_ports:
        from app.services import audit

        audit.add(
            "schema.layout_saved",
            entity="pit",
            entity_id=pit_id,
            detail=f"Сохранена ручная раскладка схемы: узлов {updated}, портов {updated_ports}",
            payload={
                "updated": updated,
                "updated_ports": updated_ports,
                "skipped": [str(x) for x in skipped],
            },
        )
    return {"updated": updated, "updated_ports": updated_ports, "skipped": skipped}


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