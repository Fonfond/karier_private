"""Библиотека блоков однолинейной схемы."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_admin
from app.db.session import get_db
from app.models import Employee
from app.schemas.gis import (
    BlockCellIn,
    BlockCellOut,
    BlockInstantiateIn,
    BlockInstantiateOut,
    SchemaBlockOut,
)
from app.services import gis
from app.services import schema_blocks as blocks_service

router = APIRouter(prefix="/schema", tags=["schema-blocks"])


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
