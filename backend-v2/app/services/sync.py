"""Синхронизация: push с разрешением конфликтов и pull по журналу изменений."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import Asset, AssetMove, ChangeLog, Conflict, Defect, Employee, SyncOp
from app.schemas.sync import ChangeOut, MoveIn, OpResultOut, PushIn, SyncOpIn
from app.services import audit, moves as moves_service

ALLOWED_ASSET_FIELDS = {"status", "grounded", "x", "y", "location_text", "attrs", "name"}
ASSET_STATUSES = {"on", "off", "standby", "maintenance", "decommissioned"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def set_actor(db: Session, actor_id: uuid.UUID) -> None:
    """Передать триггерам журнала, кто меняет данные (на уровне сессии)."""
    db.execute(
        text("select set_config('karier.actor_id', :value, false)"),
        {"value": str(actor_id)},
    )


def reset_actor(db: Session) -> None:
    try:
        db.execute(text("select set_config('karier.actor_id', '', false)"))
    except Exception:  # noqa: BLE001
        db.rollback()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _record_conflict(
    db: Session,
    *,
    asset: Asset,
    entity: str,
    kind: str,
    winner: str,
    winner_payload: dict,
    loser_payload: dict,
    client_ts: datetime | None,
    server_ts: datetime | None,
    actor: Employee,
    note: str,
) -> Conflict:
    conflict = Conflict(
        id=uuid.uuid4(),
        pit_id=asset.pit_id,
        entity=entity,
        entity_id=asset.id,
        kind=kind,
        winner=winner,
        winner_payload=winner_payload,
        loser_payload=loser_payload,
        client_ts=client_ts,
        server_ts=server_ts,
        actor_id=actor.id,
        note=note,
    )
    db.add(conflict)
    db.flush()
    audit.add(
        "sync.conflict",
        entity=entity,
        entity_id=asset.id,
        detail=f"{asset.code}: {note}",
        payload={
            "winner": winner,
            "conflict_id": str(conflict.id),
            "client_ts": client_ts.isoformat() if client_ts else None,
            "server_ts": server_ts.isoformat() if server_ts else None,
        },
    )
    return conflict


def _apply_asset_update(db: Session, op: SyncOpIn, actor: Employee) -> OpResultOut:
    if op.entity_id is None:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Не передан entity_id")

    asset = db.get(Asset, op.entity_id)
    if asset is None or asset.deleted_at is not None:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Объект не найден")

    client_ts = _aware(op.client_ts) or _now()
    server_ts = _aware(asset.updated_at)
    version_mismatch = op.base_version is not None and op.base_version != asset.version

    conflict_id: uuid.UUID | None = None
    status = "applied"

    if version_mismatch:
        client_wins = server_ts is None or client_ts > server_ts
        if not client_wins:
            conflict = _record_conflict(
                db,
                asset=asset,
                entity="asset",
                kind="version_mismatch",
                winner="server",
                winner_payload={
                    "version": asset.version,
                    "status": asset.status,
                    "grounded": asset.grounded,
                    "updated_at": server_ts.isoformat() if server_ts else None,
                },
                loser_payload={"patch": op.patch, "client_ts": client_ts.isoformat()},
                client_ts=client_ts,
                server_ts=server_ts,
                actor=actor,
                note="Изменение отклонено: на сервере более поздняя версия (LWW)",
            )
            db.commit()
            return OpResultOut(
                op_id=op.op_id,
                status="conflict_lost",
                version=asset.version,
                conflict_id=conflict.id,
                message="На сервере более свежие данные — ваше изменение сохранено в журнале конфликтов",
            )

        conflict = _record_conflict(
            db,
            asset=asset,
            entity="asset",
            kind="version_mismatch",
            winner="client",
            winner_payload={"patch": op.patch, "client_ts": client_ts.isoformat()},
            loser_payload={
                "version": asset.version,
                "status": asset.status,
                "grounded": asset.grounded,
                "updated_at": server_ts.isoformat() if server_ts else None,
            },
            client_ts=client_ts,
            server_ts=server_ts,
            actor=actor,
            note="Применено ваше изменение: оно позже серверного (LWW)",
        )
        conflict_id = conflict.id
        status = "conflict_won"

    applied: dict[str, object] = {}
    from app.services.auth import permissions_of

    perms = permissions_of(actor)
    allowed = (
        ALLOWED_ASSET_FIELDS
        if "asset.create" in perms
        else {"status", "grounded", "x", "y", "location_text"}
    )
    for field, value in op.patch.items():
        if field not in allowed:
            continue
        if field == "status" and value not in ASSET_STATUSES:
            continue
        setattr(asset, field, value)
        applied[field] = value

    if not applied and status == "applied":
        db.rollback()
        return OpResultOut(op_id=op.op_id, status="rejected", message="Нет допустимых полей для изменения")

    asset.updated_by = actor.id
    asset.version = (asset.version or 1) + 1
    db.commit()
    db.refresh(asset)

    audit.add(
        "sync.asset_updated",
        entity="asset",
        entity_id=asset.id,
        detail=f"{asset.code}: применены поля {', '.join(applied) or '—'}",
        payload={"fields": applied, "client_ts": client_ts.isoformat()},
    )
    return OpResultOut(
        op_id=op.op_id,
        status=status,  # type: ignore[arg-type]
        version=asset.version,
        conflict_id=conflict_id,
    )


def _apply_move(db: Session, op: SyncOpIn, actor: Employee) -> OpResultOut:
    if op.entity_id is None:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Не передан entity_id")

    asset = db.get(Asset, op.entity_id)
    if asset is None or asset.deleted_at is not None:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Объект не найден")
    if not asset.is_mobile:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Объект не мобильный")

    try:
        x = float(op.patch.get("x"))
        y = float(op.patch.get("y"))
    except (TypeError, ValueError):
        return OpResultOut(op_id=op.op_id, status="rejected", message="Некорректные координаты")

    client_ts = _aware(op.client_ts) or _now()
    server_ts = _aware(asset.updated_at)
    stale = server_ts is not None and client_ts < server_ts

    move = AssetMove(
        id=uuid.uuid4(),
        pit_id=asset.pit_id,
        asset_id=asset.id,
        from_x=asset.x,
        from_y=asset.y,
        to_x=x,
        to_y=y,
        moved_at=client_ts,
        moved_by=actor.id,
        note=op.patch.get("note"),
        source="offline",
        media_id=op.patch.get("media_id"),
        client_ts=client_ts,
        conflict=stale,
    )
    db.add(move)

    if stale:
        # история сохраняется, но текущее положение остаётся более поздним
        db.commit()
        conflict = _record_conflict(
            db,
            asset=asset,
            entity="move",
            kind="move_race",
            winner="server",
            winner_payload={"x": float(asset.x or 0), "y": float(asset.y or 0)},
            loser_payload={"x": x, "y": y, "client_ts": client_ts.isoformat()},
            client_ts=client_ts,
            server_ts=server_ts,
            actor=actor,
            note="Перемещение сохранено в историю, но объект уже перемещён позже",
        )
        db.commit()
        return OpResultOut(
            op_id=op.op_id,
            status="conflict_lost",
            version=asset.version,
            conflict_id=conflict.id,
            message="Перемещение записано в историю, но объект уже перемещён позже",
        )

    asset.x = x
    asset.y = y
    asset.updated_by = actor.id
    asset.version = (asset.version or 1) + 1
    db.commit()
    db.refresh(move)

    audit.add(
        "asset.moved",
        entity="asset",
        entity_id=asset.id,
        detail=f"{asset.code}: офлайн-перемещение на ({x}, {y})",
        payload={"move_id": str(move.id), "client_ts": client_ts.isoformat()},
    )
    return OpResultOut(op_id=op.op_id, status="applied", version=asset.version)


def _apply_defect_insert(db: Session, op: SyncOpIn, actor: Employee) -> OpResultOut:
    patch = op.patch
    raw_asset_id = patch.get("asset_id") or op.entity_id
    if raw_asset_id is None:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Не передан объект дефекта")

    try:
        asset_id = uuid.UUID(str(raw_asset_id))
        inspection_id = patch.get("inspection_id")
        inspection_uuid = uuid.UUID(str(inspection_id)) if inspection_id else None
    except ValueError:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Некорректный идентификатор")

    asset = db.get(Asset, asset_id)
    if asset is None:
        return OpResultOut(op_id=op.op_id, status="rejected", message="Объект не найден")

    defect = Defect(
        id=uuid.uuid4(),
        pit_id=asset.pit_id,
        asset_id=asset.id,
        inspection_id=inspection_uuid,
        severity=patch.get("severity", "medium"),
        status="open",
        category=patch.get("category", "other"),
        description=str(patch.get("description", "Без описания"))[:2000],
        detected_at=_aware(op.client_ts) or _now(),
        detected_by=actor.id,
        photo_before_id=patch.get("photo_before_id"),
    )
    db.add(defect)
    db.commit()
    db.refresh(defect)

    audit.add(
        "sync.defect_created",
        entity="defect",
        entity_id=defect.id,
        detail=f"{asset.code}: дефект из офлайн-очереди",
    )
    return OpResultOut(op_id=op.op_id, status="applied")


def push(db: Session, actor: Employee, payload: PushIn) -> dict:
    set_actor(db, actor.id)
    results: list[OpResultOut] = []

    for op in payload.ops:
        if db.get(SyncOp, op.op_id) is not None:
            results.append(
                OpResultOut(op_id=op.op_id, status="duplicate", message="Операция уже применена")
            )
            continue

        result: OpResultOut
        try:
            if op.entity == "asset" and op.op in ("update", "insert"):
                result = _apply_asset_update(db, op, actor)
            elif op.entity == "move":
                result = _apply_move(db, op, actor)
            elif op.entity == "defect" and op.op == "insert":
                result = _apply_defect_insert(db, op, actor)
            else:
                result = OpResultOut(
                    op_id=op.op_id,
                    status="rejected",
                    message=f"Неподдерживаемая операция: {op.entity}/{op.op}",
                )
        except ApiError as exc:
            db.rollback()
            result = OpResultOut(op_id=op.op_id, status="rejected", message=exc.detail)
        except Exception as exc:  # noqa: BLE001 — одна операция не должна ронять пачку
            db.rollback()
            result = OpResultOut(
                op_id=op.op_id, status="rejected", message=f"Ошибка применения: {exc}"
            )

        try:
            db.add(
                SyncOp(
                    op_id=op.op_id,
                    device_id=payload.device_id,
                    employee_id=actor.id,
                    entity=op.entity,
                    entity_id=op.entity_id,
                    status=result.status,
                )
            )
            db.commit()
        except Exception:  # noqa: BLE001 — гонка по op_id: считаем дубликатом
            db.rollback()
            result = OpResultOut(op_id=op.op_id, status="duplicate", message="Операция уже применена")

        set_actor(db, actor.id)
        results.append(result)

    seq = db.scalar(select(func.max(ChangeLog.seq))) or 0
    return {"results": results, "server_seq": int(seq)}


def pull(db: Session, since: int, limit: int = 200) -> dict:
    rows = list(
        db.scalars(
            select(ChangeLog)
            .where(ChangeLog.seq > since)
            .order_by(ChangeLog.seq)
            .limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    last_seq = rows[-1].seq if rows else since

    changes = [
        ChangeOut(
            seq=row.seq,
            entity=row.entity,
            entity_id=row.entity_id,
            op=row.op,
            payload=row.payload or {},
            actor_id=row.actor_id,
            client_ts=row.client_ts,
            server_ts=row.server_ts,
        )
        for row in rows
    ]
    return {"changes": changes, "last_seq": int(last_seq), "has_more": has_more}


def conflicts(db: Session, limit: int = 100) -> list[Conflict]:
    return list(
        db.scalars(select(Conflict).order_by(Conflict.created_at.desc()).limit(limit)).all()
    )


def conflict_out(db: Session, conflict: Conflict) -> dict:
    actor = db.get(Employee, conflict.actor_id) if conflict.actor_id else None
    return {
        "id": conflict.id,
        "entity": conflict.entity,
        "entity_id": conflict.entity_id,
        "kind": conflict.kind,
        "winner": conflict.winner,
        "winner_payload": conflict.winner_payload or {},
        "loser_payload": conflict.loser_payload or {},
        "client_ts": conflict.client_ts,
        "server_ts": conflict.server_ts,
        "note": conflict.note,
        "actor_name": actor.full_name if actor else None,
        "created_at": conflict.created_at,
    }
