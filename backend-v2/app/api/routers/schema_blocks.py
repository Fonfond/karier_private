"""Библиотека блоков однолинейной схемы."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_admin
from app.db.session import get_db
from app.models import Asset, Employee
from app.schemas.equipment import (
    CompositeBlockOut,
    CompositeCreateIn,
    CompositeCreateOut,
    CompositeCellOut,
    CompositeSectionOut,
    DisconnectorOut,
)
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
    LineChainIn,
    LineChainOut,
    LineChainPoleOut,
    LinkOut,
    SchemaBlockOut,
)
from app.services import gis
from app.services import composite as composite_service
from app.services import equipment_templates
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

@router.post(
    "/lines/chain",
    response_model=LineChainOut,
    status_code=201,
    summary="Линия между ячейками через опоры (ВЛ/кабель)",
)
def create_line_chain(
    payload: LineChainIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LineChainOut:
    from_asset = gis.get_asset(db, payload.from_asset_id)
    to_asset = gis.get_asset(db, payload.to_asset_id)
    result = blocks_service.create_line_chain(
        db,
        from_asset,
        to_asset,
        admin,
        poles=payload.poles,
        prefix=payload.prefix,
        link_type=payload.link_type,
        cable_mark=payload.cable_mark,
        line_name=payload.line_name,
        line_code=payload.line_code,
        voltage_kv=payload.voltage_kv,
    )
    line = result["line"]
    return LineChainOut(
        line_id=line.id,
        line_code=line.code,
        line_name=line.name,
        poles=[
            LineChainPoleOut(id=pole.id, code=pole.code, name=pole.name)
            for pole in result["poles"]
        ],
        link_ids=[link.id for link in result["links"]],
    )


# --- этап 2: составные устройства одним вызовом ------------------------------


def _composite_cell(cell: Asset) -> CompositeCellOut:
    attrs = cell.attrs or {}
    voltage = attrs.get("voltage_kv")
    try:
        voltage_value = round(float(voltage), 3) if voltage is not None else None
    except (TypeError, ValueError):
        voltage_value = None
    return CompositeCellOut(
        id=cell.id,
        code=cell.code,
        name=cell.name,
        type_code=cell.asset_type.code if cell.asset_type else attrs.get("cell_type", ""),
        cell_kind=cell.cell_kind or "out",
        cell_no=cell.cell_no or 0,
        section_no=cell.section_no or 1,
        status=cell.status,
        grounded=bool(cell.grounded),
        voltage_kv=voltage_value,
        local_x=float(cell.schema_local_x) if cell.schema_local_x is not None else None,
        local_y=float(cell.schema_local_y) if cell.schema_local_y is not None else None,
    )


@router.post(
    "/composite",
    response_model=CompositeCreateOut,
    status_code=201,
    summary="Создать составное устройство (БКРУ / ПС 35/6 / КТП) одной транзакцией",
)
def create_composite(
    payload: CompositeCreateIn,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CompositeCreateOut:
    result = composite_service.compose(
        db,
        admin,
        type_code=payload.type_code,
        name=payload.name,
        x=payload.x,
        y=payload.y,
        cells_per_section=payload.cells_per_section,
        code=payload.code,
    )
    parent: Asset = result["parent"]
    cells = [_composite_cell(cell) for cell in result["cells"]]
    by_id = {item.id: item for item in cells}
    sections = [
        CompositeSectionOut(
            section_no=section["section_no"],
            label=section["label"],
            voltage_kv=section["voltage_kv"],
            cells=[by_id[cell.id] for cell in section["cells"] if cell.id in by_id],
        )
        for section in result["sections"]
    ]
    disconnector = result["disconnector"]
    parsed = result["template"]
    schema_x = float(parent.schema_x) if parent.schema_x is not None else payload.x
    schema_y = float(parent.schema_y) if parent.schema_y is not None else payload.y
    disconnector_out = (
        DisconnectorOut(
            id=disconnector.id,
            code=disconnector.code,
            name=disconnector.name,
            type_code=disconnector.asset_type.code,
            cell_kind=disconnector.cell_kind or "in",
            status=disconnector.status,
            grounded=bool(disconnector.grounded),
        )
        if disconnector is not None
        else None
    )
    return CompositeCreateOut(
        id=parent.id,
        code=parent.code,
        name=parent.name,
        type_code=parent.asset_type.code,
        schema_x=schema_x,
        schema_y=schema_y,
        template_version=equipment_templates.TEMPLATE_VERSION if parsed.is_v2 else 1,
        children=result["children"],
        block=CompositeBlockOut(
            id=parent.id,
            code=parent.code,
            name=parent.name,
            type_code=parent.asset_type.code,
            schema_x=schema_x,
            schema_y=schema_y,
        ),
        sections=sections,
        cells=cells,
        disconnector=disconnector_out,
        disconnector_id=disconnector_out.id if disconnector_out is not None else None,
    )