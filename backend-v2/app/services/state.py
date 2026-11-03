"""Оперативные переключения: статус и заземление с журналом."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import Asset, Link, SwitchingOp
from app.services import audit, topology


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _count_affected(db: Session, pit_id: uuid.UUID, before: topology.Energization) -> int:
    after = topology.energize(db, pit_id)
    return len(before.energized ^ after.energized)


def change_state(
    db: Session,
    asset: Asset,
    *,
    status: str | None,
    grounded: bool | None,
    reason: str | None,
    actor,
) -> dict:
    """Изменить состояние объекта. Возвращает объект, число затронутых узлов и id операции."""
    if status is None and grounded is None:
        raise ApiError(400, "state.empty", "Не передано ни одного изменения состояния")

    if grounded is True and not (reason or "").strip():
        raise ApiError(
            422,
            "state.reason_required",
            "Для установки заземления укажите причину",
            fields={"reason": "Обязательное поле при заземлении"},
        )

    before = topology.energize(db, asset.pit_id)
    was_energized = asset.id in before.energized

    ops: list[SwitchingOp] = []

    if grounded is not None and grounded != asset.grounded:
        ops.append(
            SwitchingOp(
                id=uuid.uuid4(),
                pit_id=asset.pit_id,
                asset_id=asset.id,
                action="ground_on" if grounded else "ground_off",
                from_state="grounded" if asset.grounded else "not_grounded",
                to_state="grounded" if grounded else "not_grounded",
                reason=reason,
                performed_by=actor.id,
            )
        )
        asset.grounded = grounded

    if status is not None and status != asset.status:
        ops.append(
            SwitchingOp(
                id=uuid.uuid4(),
                pit_id=asset.pit_id,
                asset_id=asset.id,
                action="status_on" if status == "on" else "status_off",
                from_state=asset.status,
                to_state=status,
                reason=reason,
                performed_by=actor.id,
            )
        )
        asset.status = status

    if not ops:
        raise ApiError(409, "state.no_change", "Состояние уже такое — изменений нет")

    asset.version = (asset.version or 1) + 1
    asset.updated_by = actor.id
    for op in ops:
        db.add(op)
    db.commit()
    db.refresh(asset)

    affected = _count_affected(db, asset.pit_id, before)
    is_energized = asset.id in topology.energize(db, asset.pit_id).energized

    for op in ops:
        audit.add(
            f"asset.{op.action}",
            entity="asset",
            entity_id=asset.id,
            detail=f"{asset.code}: {op.from_state} → {op.to_state}"
            + (f" (причина: {reason})" if reason else ""),
            payload={"reason": reason, "switching_op_id": str(op.id)},
        )

    return {
        "asset": asset,
        "energization_changed": was_energized != is_energized,
        "affected_assets": affected,
        "switching_op_id": ops[-1].id if ops else None,
    }


def set_link_state(db: Session, link: Link, state: str, *, actor, reason: str | None = None) -> Link:
    if state not in ("connected", "open", "grounded"):
        raise ApiError(400, "link.bad_state", "Недопустимое состояние связи")
    previous = link.state
    link.state = state
    link.updated_by = actor.id
    link.version = (link.version or 1) + 1
    db.commit()
    audit.add(
        "link.state_changed",
        entity="link",
        entity_id=link.id,
        detail=f"Связь {link.from_port.asset.code}→{link.to_port.asset.code}: {previous} → {state}"
        + (f" (причина: {reason})" if reason else ""),
    )
    return link


def list_switching_ops(db: Session, pit_id: uuid.UUID, limit: int = 100) -> list[SwitchingOp]:
    return list(
        db.scalars(
            select(SwitchingOp)
            .where(SwitchingOp.pit_id == pit_id)
            .order_by(SwitchingOp.performed_at.desc())
            .limit(limit)
        ).all()
    )
