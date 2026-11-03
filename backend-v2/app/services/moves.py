"""Перемещение мобильных объектов и история перемещений."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, not_found
from app.models import Asset, AssetMove, Employee
from app.schemas.sync import MoveIn
from app.services import audit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_mobile(asset: Asset) -> None:
    if not asset.is_mobile:
        raise ApiError(
            400,
            "move.not_mobile",
            "Объект не помечен как мобильный — перемещение недоступно",
        )


def move_asset(
    db: Session,
    asset: Asset,
    payload: MoveIn,
    *,
    actor: Employee,
    source: str = "online",
) -> AssetMove:
    ensure_mobile(asset)

    move = AssetMove(
        id=uuid.uuid4(),
        pit_id=asset.pit_id,
        asset_id=asset.id,
        from_x=asset.x,
        from_y=asset.y,
        to_x=payload.x,
        to_y=payload.y,
        moved_at=payload.client_ts or _now(),
        moved_by=actor.id,
        note=payload.note,
        source=source,
        media_id=payload.media_id,
        client_ts=payload.client_ts,
    )
    db.add(move)

    asset.x = payload.x
    asset.y = payload.y
    asset.updated_by = actor.id
    asset.version = (asset.version or 1) + 1
    db.commit()
    db.refresh(move)

    audit.add(
        "asset.moved",
        entity="asset",
        entity_id=asset.id,
        detail=(
            f"{asset.code}: "
            f"({float(move.from_x) if move.from_x is not None else '—'}, "
            f"{float(move.from_y) if move.from_y is not None else '—'}) → "
            f"({payload.x}, {payload.y})"
            + (f" · {payload.note}" if payload.note else "")
        ),
        payload={"source": source, "move_id": str(move.id)},
    )
    return move


def list_moves(db: Session, asset_id: uuid.UUID, limit: int = 100) -> list[AssetMove]:
    return list(
        db.scalars(
            select(AssetMove)
            .where(AssetMove.asset_id == asset_id)
            .order_by(AssetMove.moved_at.desc())
            .limit(limit)
        ).all()
    )


def move_out(db: Session, move: AssetMove) -> dict:
    author = db.get(Employee, move.moved_by) if move.moved_by else None
    return {
        "id": move.id,
        "asset_id": move.asset_id,
        "from_x": float(move.from_x) if move.from_x is not None else None,
        "from_y": float(move.from_y) if move.from_y is not None else None,
        "to_x": float(move.to_x),
        "to_y": float(move.to_y),
        "moved_at": move.moved_at,
        "moved_by_name": author.full_name if author else None,
        "note": move.note,
        "source": move.source,
        "conflict": move.conflict,
    }


def get_move(db: Session, move_id: uuid.UUID) -> AssetMove:
    move = db.get(AssetMove, move_id)
    if move is None:
        raise not_found("Перемещение не найдено")
    return move
