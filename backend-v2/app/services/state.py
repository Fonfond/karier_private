"""Оперативные переключения: статус и заземление с журналом."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import Asset, Link, SwitchingOp
from app.services import asset_fields, audit, topology


TOGGLEABLE_STATUSES = ("on", "off")
CELL_KINDS = ("in", "out", "sectional")


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


def nominal_voltage_kv(asset: Asset) -> float | None:
    """Номинальное напряжение объекта: attrs → порты (ввод) → любые порты.

    Для составных устройств этапа 2 напряжение пишется в ``attrs.voltage_kv``
    ячейки (например, секция 2 ПС 35/6 — 6 кВ), поэтому attrs приоритетнее портов.
    """
    attrs = asset.attrs or {}
    for key in ("voltage_kv", "voltage_out_kv", "voltage_in_kv"):
        raw = attrs.get(key)
        if raw is None or raw == "":
            continue
        try:
            return round(float(raw), 3)
        except (TypeError, ValueError):
            continue
    ports = [port for port in asset.ports if port.nominal_voltage_kv is not None]
    incoming = [float(port.nominal_voltage_kv) for port in ports if port.kind in ("in", "io")]
    if incoming:
        return round(max(incoming), 3)
    if ports:
        return round(max(float(port.nominal_voltage_kv) for port in ports), 3)
    return None


def is_toggleable(asset: Asset) -> bool:
    """Переключать можно ячейки ПС/БКРУ и коммутационные аппараты."""
    if asset.cell_kind in CELL_KINDS:
        return True
    return asset_fields.effective_class(asset.asset_type) == "switching"


def _require_toggleable(asset: Asset) -> None:
    if is_toggleable(asset):
        return
    raise ApiError(
        422,
        "asset.not_switchable",
        "Переключать можно ячейки и коммутационные аппараты (разъединители, рубильники)",
    )


def toggle_asset(
    db: Session,
    asset: Asset,
    *,
    state: str | None,
    reason: str | None,
    actor,
) -> dict:
    """Этап 2: включить/отключить ячейку или разъединитель.

    Возвращает ``{status, energized, voltage_kv, grounded, previous_status, …}``.
    ``energized`` здесь — оперативное «под напряжением» для кнопки и цвета на
    схеме: объект включён и не заземлён. Графовая достижимость от источника
    отдаётся отдельным полем ``topology_energized`` (она может быть False, пока
    ячейка не подключена связями).
    """
    _require_toggleable(asset)

    previous_status = asset.status
    target = (state or "").strip().lower() or ("off" if previous_status == "on" else "on")
    if target not in TOGGLEABLE_STATUSES:
        raise ApiError(
            422,
            "asset.bad_state",
            "Допустимые состояния переключения: on, off",
            fields={"state": "Допустимо on или off"},
        )
    if reason is not None:
        reason = reason.strip()[:255] or None

    changed = target != previous_status
    if changed:
        db.add(
            SwitchingOp(
                id=uuid.uuid4(),
                pit_id=asset.pit_id,
                asset_id=asset.id,
                action="status_on" if target == "on" else "status_off",
                from_state=previous_status,
                to_state=target,
                reason=reason,
                performed_by=actor.id,
            )
        )
        asset.status = target
        asset.updated_by = actor.id
        asset.version = (asset.version or 1) + 1
        db.commit()
        db.refresh(asset)

    nominal = nominal_voltage_kv(asset)
    energized = asset.status == "on" and not asset.grounded
    voltage_kv = round(float(nominal), 3) if energized and nominal is not None else 0.0
    topology_energized = asset.id in topology.energize(db, asset.pit_id).energized

    detail = f"{asset.code}: {previous_status} → {asset.status}"
    if reason:
        detail += f" (причина: {reason})"
    audit.add(
        "asset.toggled",
        entity="asset",
        entity_id=asset.id,
        detail=detail,
        payload={
            "from_state": previous_status,
            "to_state": asset.status,
            # алиасы для читаемости в журнале/отчётах: прежнее и новое состояние
            "from": previous_status,
            "to": asset.status,
            "reason": reason,
            "energized": energized,
            "voltage_kv": voltage_kv,
            "grounded": asset.grounded,
            "cell_kind": asset.cell_kind,
            "changed": changed,
        },
    )
    return {
        "asset": asset,
        "previous_status": previous_status,
        "status": asset.status,
        "changed": changed,
        "energized": energized,
        "voltage_kv": voltage_kv,
        "nominal_voltage_kv": nominal,
        "grounded": bool(asset.grounded),
        "topology_energized": topology_energized,
    }


def list_switching_ops(db: Session, pit_id: uuid.UUID, limit: int = 100) -> list[SwitchingOp]:
    return list(
        db.scalars(
            select(SwitchingOp)
            .where(SwitchingOp.pit_id == pit_id)
            .order_by(SwitchingOp.performed_at.desc())
            .limit(limit)
        ).all()
    )
