"""Аналитика для дашборда."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, AssetMove, Defect, Inspection, InspectionItem, Pit
from app.services import topology

WEEK = timedelta(days=7)


def dashboard_summary(db: Session, pit: Pit) -> dict:
    assets = list(
        db.scalars(
            select(Asset).where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
        ).unique().all()
    )
    asset_ids = [asset.id for asset in assets]

    energization = topology.energize(db, pit.id)
    energized = [asset for asset in assets if asset.id in energization.energized]

    by_status: dict[str, int] = {}
    for asset in assets:
        by_status[asset.status] = by_status.get(asset.status, 0) + 1

    by_type: dict[str, int] = {}
    for asset in assets:
        code = asset.asset_type.code if asset.asset_type else "unknown"
        by_type[code] = by_type.get(code, 0) + 1

    open_defects = list(
        db.scalars(
            select(Defect).where(Defect.pit_id == pit.id, Defect.status.in_(("open", "in_progress")))
        ).all()
    )
    defects_by_severity: dict[str, int] = {}
    defects_by_category: dict[str, int] = {}
    for defect in open_defects:
        defects_by_severity[defect.severity] = defects_by_severity.get(defect.severity, 0) + 1
        category = defect.category or "other"
        defects_by_category[category] = defects_by_category.get(category, 0) + 1

    now = datetime.now(timezone.utc)
    week_ago = now - WEEK

    week_inspections = db.scalar(
        select(func.count(Inspection.id)).where(
            Inspection.pit_id == pit.id, Inspection.started_at >= week_ago
        )
    ) or 0

    week_defects = db.scalar(
        select(func.count(Defect.id)).where(
            Defect.pit_id == pit.id, Defect.detected_at >= week_ago
        )
    ) or 0

    checked_items = db.scalar(
        select(func.count(InspectionItem.id))
        .join(Inspection, InspectionItem.inspection_id == Inspection.id)
        .where(Inspection.pit_id == pit.id, InspectionItem.result.is_not(None))
    ) or 0

    mobile: list[dict] = []
    for asset in assets:
        if not asset.is_mobile:
            continue
        last_move = db.scalar(
            select(AssetMove)
            .where(AssetMove.asset_id == asset.id)
            .order_by(AssetMove.moved_at.desc())
            .limit(1)
        )
        moved_at = last_move.moved_at if last_move else None
        days = None
        if moved_at is not None:
            days = max(0, (now - moved_at).days)
        mobile.append(
            {
                "id": str(asset.id),
                "code": asset.code,
                "name": asset.name,
                "status": asset.status,
                "x": float(asset.x) if asset.x is not None else None,
                "y": float(asset.y) if asset.y is not None else None,
                "moved_at": moved_at.isoformat() if moved_at else None,
                "days_since_move": days,
                "last_note": last_move.note if last_move else None,
            }
        )
    mobile.sort(key=lambda item: (item["days_since_move"] is None, -(item["days_since_move"] or 0)))

    fixed_week = db.scalar(
        select(func.count(Defect.id)).where(
            Defect.pit_id == pit.id, Defect.fixed_at.is_not(None), Defect.fixed_at >= week_ago
        )
    ) or 0

    return {
        "generated_at": now.isoformat(),
        "assets": {
            "total": len(assets),
            "energized": len(energized),
            "deenergized": len(assets) - len(energized),
            "grounded": sum(1 for asset in assets if asset.grounded),
            "by_status": by_status,
            "by_type": by_type,
        },
        "defects": {
            "open": len(open_defects),
            "by_severity": defects_by_severity,
            "by_category": defects_by_category,
            "fixed_last_week": int(fixed_week),
        },
        "inspections": {
            "week": int(week_inspections),
            "week_defects": int(week_defects),
            "checked_items": int(checked_items),
            "total": int(
                db.scalar(
                    select(func.count(Inspection.id)).where(Inspection.pit_id == pit.id)
                )
                or 0
            ),
        },
        "mobile": mobile,
        "asset_ids": len(asset_ids),
    }
