"""ГИС-реестр, топология, переключения и однолинейная схема."""

from __future__ import annotations

import uuid as uuidlib
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_admin, require_permission
from app.core.errors import not_found
from app.db.session import get_db
from app.models import Asset, AssetType, Employee, Line, Link
from app.schemas.gis import (
    AssetCreate,
    AssetListOut,
    AssetOut,
    AssetTypeCreate,
    AssetTypeOut,
    AssetTypeUpdate,
    AssetUpdate,
    ChildAssetOut,
    GraphBlockChildOut,
    GraphBlockOut,
    GraphEdgeOut,
    GraphNodeOut,
    LineCreate,
    LineOut,
    LinkCreate,
    LinkListOut,
    LinkOut,
    LinkUpdate,
    MapLayerOut,
    PortRefOut,
    PowerPathNode,
    PowerPathOut,
    SchemaFrameIn,
    SchemaFrameOut,
    SchemaLayoutIn,
    SchemaLayoutOut,
    StateChangeIn,
    StateChangeOut,
    TopologyGraphOut,
    TopologyIssueOut,
)
from app.services import audit, documents as documents_service, gis, links as links_service
from app.services import state as state_service
from app.services import schema_pdf as schema_pdf_service
from app.services import topology

router = APIRouter(tags=["gis"])


# --- типы объектов ---------------------------------------------------------

@router.get("/asset-types", response_model=list[AssetTypeOut], summary="Справочник типов")
def list_asset_types(
    include_inactive: bool = Query(default=False, description="Показать и архивные типы"),
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[AssetTypeOut]:
    return [
        AssetTypeOut(**gis.type_out(db, item))
        for item in gis.list_types(db, include_inactive=include_inactive)
    ]


@router.post(
    "/asset-types", response_model=AssetTypeOut, status_code=201, summary="Добавить тип (админ)"
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
    return AssetTypeOut(**gis.type_out(db, asset_type))


@router.patch(
    "/asset-types/{type_id}", response_model=AssetTypeOut, summary="Изменить тип (админ)"
)
def patch_asset_type(
    type_id: uuidlib.UUID,
    payload: AssetTypeUpdate,
    _: Employee = Depends(require_permission("settings.edit")),
    db: Session = Depends(get_db),
) -> AssetTypeOut:
    asset_type = db.get(AssetType, type_id)
    if asset_type is None:
        raise not_found("Тип не найден")
    updated = gis.update_type(db, asset_type, payload)
    audit.add(
        "asset_type.updated", entity="asset_type", entity_id=updated.id, detail=f"Изменён тип {updated.code}"
    )
    return AssetTypeOut(**gis.type_out(db, updated))


@router.delete("/asset-types/{type_id}", response_model=AssetTypeOut, summary="Архивировать тип (админ)")
def delete_asset_type(
    type_id: uuidlib.UUID,
    _: Employee = Depends(require_permission("settings.edit")),
    db: Session = Depends(get_db),
) -> AssetTypeOut:
    asset_type = db.get(AssetType, type_id)
    if asset_type is None:
        raise not_found("Тип не найден")
    gis.deactivate_type(db, asset_type)
    audit.add(
        "asset_type.deactivated",
        entity="asset_type",
        entity_id=asset_type.id,
        detail=f"Тип {asset_type.code} переведён в архив",
    )
    return AssetTypeOut(**gis.type_out(db, asset_type))


# --- объекты ---------------------------------------------------------------

@router.get("/assets", response_model=AssetListOut, summary="Список объектов")
def list_assets(
    q: str | None = Query(default=None, max_length=128),
    type_code: str | None = Query(default=None, max_length=48),
    status: str | None = Query(default=None, max_length=24),
    is_mobile: bool | None = Query(default=None),
    parent_id: uuidlib.UUID | None = Query(default=None),
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
        parent_id=parent_id,
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
        payload={
            "code": asset.code,
            "type": asset.asset_type.code,
            "x": float(asset.x) if asset.x is not None else None,
            "y": float(asset.y) if asset.y is not None else None,
        },
    )
    return gis.asset_full(asset)


@router.get("/assets/{asset_id}", response_model=AssetOut, summary="Карточка объекта")
def get_asset(
    asset_id: uuidlib.UUID,
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> AssetOut:
    return gis.asset_full(gis.get_asset(db, asset_id))


@router.get(
    "/assets/{asset_id}/children",
    response_model=list[ChildAssetOut],
    summary="Внутренняя структура: секции, ячейки",
)
def asset_children(
    asset_id: uuidlib.UUID,
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[ChildAssetOut]:
    gis.get_asset(db, asset_id)
    energization = topology.energize(db, gis.get_pit(db).id)
    rows = db.scalars(
        select(Asset)
        .where(Asset.parent_asset_id == asset_id, Asset.deleted_at.is_(None))
        .order_by(Asset.code)
    ).unique().all()
    return [
        ChildAssetOut(
            id=child.id,
            code=child.code,
            name=child.name,
            type_code=child.asset_type.code,
            type_icon=child.asset_type.icon,
            type_name=child.asset_type.name,
            status=child.status,
            grounded=child.grounded,
            energized=child.id in energization.energized,
            ports=[
                PortRefOut(
                    id=p.id,
                    code=p.code,
                    name=p.name,
                    kind=p.kind,
                    voltage_kv=float(p.nominal_voltage_kv) if p.nominal_voltage_kv else None,
                )
                for p in child.ports
            ],
        )
        for child in rows
    ]


@router.patch("/assets/{asset_id}", response_model=AssetOut, summary="Изменить объект")
def patch_asset(
    asset_id: uuidlib.UUID,
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


@router.post(
    "/assets/{asset_id}/state",
    response_model=StateChangeOut,
    summary="Переключение: статус и заземление",
)
def change_asset_state(
    asset_id: uuidlib.UUID,
    payload: StateChangeIn,
    user: Employee = Depends(require_permission("asset.status.edit")),
    db: Session = Depends(get_db),
) -> StateChangeOut:
    asset = gis.get_asset(db, asset_id)
    result = state_service.change_state(
        db,
        asset,
        status=payload.status,
        grounded=payload.grounded,
        reason=payload.reason,
        actor=user,
    )
    updated = gis.get_asset(db, asset.id)
    return StateChangeOut(
        asset=gis.asset_full(updated),
        energization_changed=result["energization_changed"],
        affected_assets=result["affected_assets"],
        switching_op_id=result["switching_op_id"],
    )


@router.delete("/assets/{asset_id}", summary="Удалить объект (мягко)")
def delete_asset(
    asset_id: uuidlib.UUID,
    user: Employee = Depends(require_permission("asset.delete")),
    db: Session = Depends(get_db),
) -> dict:
    asset = gis.get_asset(db, asset_id)
    code, name = asset.code, asset.name
    gis.soft_delete(db, asset, actor=user)
    audit.add(
        "asset.deleted", entity="asset", entity_id=asset_id, detail=f"Удалён объект {code} ({name})"
    )
    return {"message": "Объект удалён", "id": str(asset_id)}


# --- путь питания ----------------------------------------------------------

def _path_node(node: dict, role: str) -> PowerPathNode:
    asset = node["asset"]
    link: Link | None = node.get("link")
    return PowerPathNode(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        type_code=asset.asset_type.code if asset.asset_type else None,
        type_name=asset.asset_type.name if asset.asset_type else None,
        type_icon=asset.asset_type.icon if asset.asset_type else None,
        role=role,
        link_id=link.id if link else None,
        link_label=links_service.link_label(link) if link else None,
        link_state=link.state if link else None,
    )


@router.get(
    "/assets/{asset_id}/power-path",
    response_model=PowerPathOut,
    summary="Путь питания по графу связей",
)
def asset_power_path(
    asset_id: uuidlib.UUID,
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> PowerPathOut:
    asset = gis.get_asset(db, asset_id)
    data = topology.power_path(db, asset)

    chain: list[PowerPathNode] = []
    nodes = data["nodes"]
    for index, node in enumerate(nodes):
        if index == 0:
            role = "source"
        elif index == len(nodes) - 1:
            role = "asset"
        else:
            role = "feed"
        chain.append(_path_node(node, role))

    source_asset = data["source"]
    source = None
    if source_asset is not None:
        source = PowerPathNode(
            id=source_asset.id,
            code=source_asset.code,
            name=source_asset.name,
            type_code=source_asset.asset_type.code if source_asset.asset_type else None,
            type_name=source_asset.asset_type.name if source_asset.asset_type else None,
            type_icon=source_asset.asset_type.icon if source_asset.asset_type else None,
            role="source",
        )

    return PowerPathOut(
        asset_id=asset.id,
        asset_name=asset.name,
        energized=data["energized"],
        source=source,
        chain=chain,
        reason=data["reason"],
        note="Расчёт по графу связей: обход от включённых источников по включённым связям и объектам.",
    )


# --- связи -----------------------------------------------------------------

@router.get("/links", response_model=LinkListOut, summary="Список связей")
def list_links(
    asset_id: uuidlib.UUID | None = Query(default=None),
    state: str | None = Query(default=None, max_length=16),
    link_type: str | None = Query(default=None, max_length=16),
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> LinkListOut:
    pit = gis.get_pit(db)
    rows = links_service.list_links(
        db, pit.id, asset_id=asset_id, state=state, link_type=link_type
    )
    return LinkListOut(items=[links_service.link_out(link) for link in rows], total=len(rows))


@router.post("/links", response_model=LinkOut, status_code=201, summary="Создать связь")
def create_link(
    payload: LinkCreate,
    user: Employee = Depends(require_permission("topology.edit")),
    db: Session = Depends(get_db),
) -> LinkOut:
    pit = gis.get_pit(db)
    return links_service.create_link(db, pit.id, payload, actor=user)


@router.patch("/links/{link_id}", response_model=LinkOut, summary="Изменить связь")
def patch_link(
    link_id: uuidlib.UUID,
    payload: LinkUpdate,
    user: Employee = Depends(require_permission("topology.edit")),
    db: Session = Depends(get_db),
) -> LinkOut:
    link = links_service.get_link(db, link_id)
    return links_service.update_link(db, link, payload, actor=user)


@router.post("/links/{link_id}/state", response_model=LinkOut, summary="Переключить связь")
def switch_link(
    link_id: uuidlib.UUID,
    payload: dict[str, Any],
    user: Employee = Depends(require_permission("asset.status.edit")),
    db: Session = Depends(get_db),
) -> LinkOut:
    link = links_service.get_link(db, link_id)
    updated = state_service.set_link_state(
        db, link, str(payload.get("state", "open")), actor=user, reason=payload.get("reason")
    )
    return links_service.link_out(updated)


@router.delete("/links/{link_id}", summary="Удалить связь")
def delete_link(
    link_id: uuidlib.UUID,
    user: Employee = Depends(require_permission("topology.edit")),
    db: Session = Depends(get_db),
) -> dict:
    link = links_service.get_link(db, link_id)
    links_service.delete_link(db, link, actor=user)
    return {"message": "Связь удалена", "id": str(link_id)}


# --- линии -----------------------------------------------------------------

@router.get("/lines", response_model=list[LineOut], summary="Линии (фидеры)")
def list_lines(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[LineOut]:
    pit = gis.get_pit(db)
    return links_service.list_lines(db, pit.id)


@router.post("/lines", response_model=LineOut, status_code=201, summary="Создать линию")
def create_line(
    payload: LineCreate,
    user: Employee = Depends(require_permission("topology.edit")),
    db: Session = Depends(get_db),
) -> LineOut:
    pit = gis.get_pit(db)
    return links_service.create_line(db, pit.id, payload, actor=user)


# --- схема и проверки ------------------------------------------------------

@router.get("/topology/graph", response_model=TopologyGraphOut, summary="Граф для схемы")
def topology_graph(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> TopologyGraphOut:
    pit = gis.get_pit(db)
    data = topology.graph_payload(db, pit.id)

    blocks_map: dict = {}
    for item in data["nodes"]:
        asset = item["asset"]
        if asset.schema_block_id is not None:
            block = blocks_map.setdefault(
                asset.schema_block_id,
                {"parent": None, "children": []},
            )
            block["children"].append(
                GraphBlockChildOut(
                    id=asset.id,
                    code=asset.code,
                    name=asset.name,
                    role=asset.schema_role,
                    local_x=float(asset.schema_local_x) if asset.schema_local_x is not None else None,
                    local_y=float(asset.schema_local_y) if asset.schema_local_y is not None else None,
                    type_name=asset.asset_type.name if asset.asset_type else None,
                    params=asset.attrs or {},
                )
            )

    nodes = [
        GraphNodeOut(
            id=item["asset"].id,
            code=item["asset"].code,
            name=item["asset"].name,
            type_code=item["asset"].asset_type.code,
            type_name=item["asset"].asset_type.name,
            type_icon=item["asset"].asset_type.icon,
            type_color=item["asset"].asset_type.color,
            category=item["asset"].asset_type.category,
            schema_symbol=item["asset"].asset_type.schema_symbol,
            status=item["asset"].status,
            grounded=item["asset"].grounded,
            energized=item["energized"],
            is_source=item["is_source"],
            parent_id=item["asset"].parent_asset_id,
            schema_x=float(item["asset"].schema_x) if item["asset"].schema_x is not None else None,
            schema_y=float(item["asset"].schema_y) if item["asset"].schema_y is not None else None,
            ports=[
                PortRefOut(
                    id=p.id,
                    code=p.code,
                    name=p.name,
                    kind=p.kind,
                    voltage_kv=float(p.nominal_voltage_kv) if p.nominal_voltage_kv else None,
                    schema_x=float(p.schema_x) if p.schema_x is not None else None,
                    schema_y=float(p.schema_y) if p.schema_y is not None else None,
                )
                for p in item["asset"].ports
            ],
        )
        for item in data["nodes"]
        if item["asset"].schema_block_id is None
    ]
    edges = [
        GraphEdgeOut(
            id=item["link"].id,
            from_asset_id=item["from_asset_id"],
            to_asset_id=item["to_asset_id"],
            label=links_service.link_label(item["link"]),
            link_type=item["link"].link_type,
            state=item["link"].state,
            feed_role=item["link"].feed_role,
            cable_mark=item["link"].cable_mark,
            length_m=float(item["link"].length_m) if item["link"].length_m else None,
            cross_section_mm2=(
                float(item["link"].cross_section_mm2) if item["link"].cross_section_mm2 else None
            ),
            cores=item["link"].cores,
            version=item["link"].version,
        )
        for item in data["edges"]
    ]

    blocks = []
    for block_id, bucket in blocks_map.items():
        parent_asset = next(
            (item["asset"] for item in data["nodes"] if item["asset"].id == block_id), None
        )
        if parent_asset is None:
            continue
        blocks.append(
            GraphBlockOut(
                asset_id=parent_asset.id,
                code=parent_asset.code,
                name=parent_asset.name,
                block_code=(parent_asset.attrs or {}).get("block_code"),
                schema_x=float(parent_asset.schema_x) if parent_asset.schema_x is not None else None,
                schema_y=float(parent_asset.schema_y) if parent_asset.schema_y is not None else None,
                children=bucket["children"],
            )
        )

    return TopologyGraphOut(nodes=nodes, edges=edges, blocks=blocks)


@router.put(
    "/topology/layout",
    response_model=SchemaLayoutOut,
    summary="Сохранить ручную раскладку схемы (только админ)",
)
def save_schema_layout(
    payload: SchemaLayoutIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchemaLayoutOut:
    pit = gis.get_pit(db)
    result = gis.set_schema_layout(
        db,
        pit.id,
        [item.model_dump() for item in payload.items],
        admin,
        ports=[item.model_dump() for item in payload.ports],
    )
    return SchemaLayoutOut(**result)


@router.get("/topology/frame", response_model=SchemaFrameOut, summary="Рамка и штамп схемы")
def get_schema_frame(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> SchemaFrameOut:
    pit = gis.get_pit(db)
    return SchemaFrameOut(**gis.get_schema_frame(db, pit))


@router.put("/topology/frame", response_model=SchemaFrameOut, summary="Изменить штамп (админ)")
def save_schema_frame(
    payload: SchemaFrameIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchemaFrameOut:
    pit = gis.get_pit(db)
    data = gis.save_schema_frame(db, pit, payload.model_dump())
    audit.add(
        "schema.frame_saved",
        entity="pit",
        entity_id=pit.id,
        detail=f"Обновлён штамп схемы: {data.get('object_name', '')[:60]}",
    )
    return SchemaFrameOut(**data)


@router.get("/topology/schema.pdf", summary="Печать схемы в PDF (A3, рамка и штамп)")
def schema_pdf(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    pit = gis.get_pit(db)
    data = schema_pdf_service.schema_pdf(db, pit)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="karier-schema.pdf"'},
    )


@router.get("/topology/issues", response_model=list[TopologyIssueOut], summary="Проверки схемы")
def topology_issues(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[TopologyIssueOut]:
    pit = gis.get_pit(db)
    return [TopologyIssueOut(**issue) for issue in topology.topology_issues(db, pit.id)]


@router.get("/topology/switching", summary="Журнал переключений")
def switching_log(
    limit: int = Query(default=100, ge=1, le=500),
    _: Employee = Depends(require_permission("asset.status.edit")),
    db: Session = Depends(get_db),
) -> dict:
    pit = gis.get_pit(db)
    rows = state_service.list_switching_ops(db, pit.id, limit=limit)
    return {
        "items": [
            {
                "id": str(row.id),
                "asset_id": str(row.asset_id),
                "asset_code": row.asset.code if row.asset else None,
                "asset_name": row.asset.name if row.asset else None,
                "action": row.action,
                "from_state": row.from_state,
                "to_state": row.to_state,
                "reason": row.reason,
                "performed_at": row.performed_at,
            }
            for row in rows
        ],
        "total": len(rows),
    }


# --- документы объекта -----------------------------------------------------

@router.get("/assets/{asset_id}/documents", summary="Документы объекта")
def list_asset_documents(
    asset_id: uuidlib.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    gis.get_asset(db, asset_id)
    rows = documents_service.list_documents(db, asset_id)
    return {
        "items": [
            documents_service.document_out(db, doc, employee_id=str(user.id)) for doc in rows
        ],
        "total": len(rows),
    }


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
