"""Библиотека блоков однолинейной схемы."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_admin
from app.db.session import get_db
from app.models import Employee
from app.schemas.gis import (
    BlockCellIn,
    BlockCellOut,
    BlockCollapseIn,
    BlockJumperIn,
    LegendItemOut,
    BlockInstantiateIn,
    BlockInstantiateOut,
    AssetOut,
    ContourIn,
    ContourOut,
    PlaceAssetIn,
    BulkCellsIn,
    BulkCellsOut,
    CellCableIn,
    LineEquipmentIn,
    LineEquipmentOut,
    LinkOut,
    SchemaBlockOut,
)
from app.services import gis
from app.services import schema_blocks as blocks_service

router = APIRouter(prefix="/schema", tags=["schema-blocks"])


class RelocateIn(BaseModel):
    """Куда переносим: блок/контур или None (вернуть на схему без контейнера)."""

    target_asset_id: uuid.UUID | None = None
    confirm: bool = False
    x: float | None = None
    y: float | None = None
    local_x: float | None = None
    local_y: float | None = None


class RelocateOut(BaseModel):
    asset: AssetOut
    warnings: list[str] = []
    old_parent_id: uuid.UUID | None = None
    old_block_id: uuid.UUID | None = None
    old_local_x: float | None = None
    old_local_y: float | None = None
    old_schema_x: float | None = None
    old_schema_y: float | None = None


@router.get("/blocks", response_model=list[SchemaBlockOut], summary="Библиотека блоков схемы")
def list_blocks(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SchemaBlockOut]:
    return [
        SchemaBlockOut(**blocks_service.block_summary(db, block))
        for block in blocks_service.list_blocks(db)
    ]


@router.post(
    "/blocks/{code}/instantiate",
    response_model=BlockInstantiateOut,
    status_code=201,
    summary="Поставить блок на схему (создаёт объекты)",
)
def instantiate_block(
    code: str,
    payload: BlockInstantiateIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BlockInstantiateOut:
    block = blocks_service.get_block(db, code)
    result = blocks_service.instantiate(
        db, block, admin, x=payload.x, y=payload.y, name=payload.name
    )
    return BlockInstantiateOut(**result)


@router.post(
    "/assets/{asset_id}/cells",
    response_model=BlockCellOut,
    status_code=201,
    summary="Добавить ячейку в блок",
)
def add_cell(
    asset_id: uuid.UUID,
    payload: BlockCellIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BlockCellOut:
    parent = gis.get_asset(db, asset_id)
    cell = blocks_service.add_cell(
        db,
        parent,
        admin,
        label=payload.label,
        params=payload.params,
        role=payload.role,
        type_code=payload.type_code,
        x=payload.x,
        y=payload.y,
    )
    return BlockCellOut(
        id=cell.id, code=cell.code, name=cell.name, role=cell.schema_role
    )


@router.delete(
    "/assets/{asset_id}/cells/{cell_id}",
    summary="Удалить ячейку блока (структурные защищены)",
)
def delete_cell(
    asset_id: uuid.UUID,
    cell_id: uuid.UUID,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    parent = gis.get_asset(db, asset_id)
    cell = gis.get_asset(db, cell_id)
    blocks_service.remove_cell(db, parent, cell, admin)
    return {"message": "Ячейка удалена", "id": str(cell_id)}

@router.post(
    "/contours",
    response_model=ContourOut,
    status_code=201,
    summary="Создать прямоугольный контур на схеме (и объект в реестре)",
)
def create_contour(
    payload: ContourIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ContourOut:
    asset = blocks_service.create_contour(
        db,
        name=payload.name,
        type_code=payload.type_code,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
        comment=payload.comment,
        actor=admin,
    )
    return ContourOut(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        type_code=asset.asset_type.code,
        x=float(asset.schema_x or 0),
        y=float(asset.schema_y or 0),
        width=float((asset.attrs or {}).get("contour_w") or payload.width),
        height=float((asset.attrs or {}).get("contour_h") or payload.height),
    )


@router.post(
    "/assets/{asset_id}/place",
    response_model=AssetOut,
    summary="Поставить существующий объект реестра на схему",
)
def place_asset(
    asset_id: uuid.UUID,
    payload: PlaceAssetIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = gis.get_asset(db, asset_id)
    updated = blocks_service.place_on_schema(db, asset, x=payload.x, y=payload.y, actor=admin)
    return gis.asset_full(updated)

@router.delete(
    "/assets/{asset_id}/place",
    response_model=AssetOut,
    summary="Убрать объект со схемы (в реестре остаётся)",
)
def unplace_asset(
    asset_id: uuid.UUID,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = gis.get_asset(db, asset_id)
    updated = blocks_service.unplace_from_schema(db, asset, actor=admin)
    return gis.asset_full(updated)

@router.post(
    "/assets/{asset_id}/relocate",
    response_model=RelocateOut,
    summary="Перенести объект/ячейку в другой блок или контур (атомарно)",
)
def relocate_asset(
    asset_id: uuid.UUID,
    payload: RelocateIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RelocateOut:
    asset = gis.get_asset(db, asset_id)
    target = gis.get_asset(db, payload.target_asset_id) if payload.target_asset_id else None
    result = blocks_service.relocate(
        db,
        asset,
        target,
        actor=admin,
        confirm=payload.confirm,
        x=payload.x,
        y=payload.y,
        local_x=payload.local_x,
        local_y=payload.local_y,
    )
    return RelocateOut(
        asset=gis.asset_full(result["asset"]),
        warnings=result["warnings"],
        old_parent_id=result["old_parent_id"],
        old_block_id=result["old_block_id"],
        old_local_x=result["old_local_x"],
        old_local_y=result["old_local_y"],
        old_schema_x=result["old_schema_x"],
        old_schema_y=result["old_schema_y"],
    )


@router.post("/assets/{asset_id}/collapse", summary="Свернуть/развернуть блок")
def collapse_block(
    asset_id: uuid.UUID,
    payload: BlockCollapseIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    parent = gis.get_asset(db, asset_id)
    collapsed = blocks_service.set_collapsed(db, parent, payload.collapsed, admin)
    return {"asset_id": str(asset_id), "collapsed": collapsed}


@router.post("/assets/{asset_id}/jumpers", summary="Перемычка между ячейками одного блока")
def create_jumper(
    asset_id: uuid.UUID,
    payload: BlockJumperIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    parent = gis.get_asset(db, asset_id)
    return blocks_service.create_jumper(
        db,
        parent,
        payload.from_cell_id,
        payload.to_cell_id,
        admin,
        label=payload.label,
    )


@router.get("/legend", response_model=list[LegendItemOut], summary="Легенда символов схемы")
def legend(
    _: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[LegendItemOut]:
    return [LegendItemOut(**item) for item in blocks_service.legend(db)]


# --- построение линии: пачки ячеек, кабели, оборудование ---------------------

@router.post(
    "/assets/{asset_id}/cells/bulk",
    response_model=BulkCellsOut,
    status_code=201,
    summary="Добавить пачку ячеек со сквозной нумерацией и секциями",
)
def add_cells_bulk(
    asset_id: uuid.UUID,
    payload: BulkCellsIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BulkCellsOut:
    parent = gis.get_asset(db, asset_id)
    created = blocks_service.add_cells_bulk(
        db,
        parent,
        admin,
        count=payload.count,
        start=payload.start,
        prefix=payload.prefix,
        suffix=payload.suffix,
        section_size=payload.section_size,
        section_prefix=payload.section_prefix,
        role=payload.role,
        type_code=payload.type_code,
    )
    sections: list[str] = []
    for cell in created:
        section = (cell.attrs or {}).get("section")
        if section and section not in sections:
            sections.append(str(section))
    return BulkCellsOut(
        parent_id=parent.id,
        count=len(created),
        sections=sections,
        items=[
            BlockCellOut(id=cell.id, code=cell.code, name=cell.name, role=cell.schema_role)
            for cell in created
        ],
    )


@router.post(
    "/assets/{asset_id}/cables",
    response_model=LinkOut,
    status_code=201,
    summary="Отходящий кабель от ячейки/узла до объекта (порты подбираются)",
)
def create_cable(
    asset_id: uuid.UUID,
    payload: CellCableIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LinkOut:
    from_asset = gis.get_asset(db, asset_id)
    to_asset = gis.get_asset(db, payload.to_asset_id)
    return blocks_service.create_cable(
        db,
        from_asset,
        to_asset,
        admin,
        from_port_id=payload.from_port_id,
        to_port_id=payload.to_port_id,
        cable_mark=payload.cable_mark,
        length_m=payload.length_m,
        cross_section_mm2=payload.cross_section_mm2,
        cores=payload.cores,
        link_type=payload.link_type,
    )


@router.post(
    "/line-equipment",
    response_model=LineEquipmentOut,
    status_code=201,
    summary="Добавить КТП/ЯКУ/разъединитель в линию к опоре",
)
def add_line_equipment(
    payload: LineEquipmentIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LineEquipmentOut:
    anchor = gis.get_asset(db, payload.anchor_asset_id)
    result = blocks_service.add_line_equipment(
        db,
        anchor,
        admin,
        type_code=payload.type_code,
        name=payload.name,
        cable_mark=payload.cable_mark,
        link_type=payload.link_type,
    )
    asset = result["asset"]
    link = result["link"]
    return LineEquipmentOut(
        asset_id=asset.id,
        code=asset.code,
        name=asset.name,
        type_code=asset.asset_type.code,
        link_id=link.id,
        schema_x=float(asset.schema_x) if asset.schema_x is not None else None,
        schema_y=float(asset.schema_y) if asset.schema_y is not None else None,
    )