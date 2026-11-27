"""Снимки однолинейной схемы: создание, чтение, публикация.

Снимок — неизменяемый слепок состояния схемы на дату. Живая схема продолжает
меняться; опубликованный снимок фиксирует согласованную версию (кто и когда
опубликовал), но сам слепок не переписывается.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, conflict, not_found
from app.models import Employee, Pit, SchemaSnapshot
from app.schemas.gis import (
    SnapshotBriefOut,
    SnapshotCreate,
    SnapshotOut,
)
from app.services import audit
from app.services import schema_graph


def _author_name(db: Session, employee_id: uuid.UUID | None) -> str | None:
    if employee_id is None:
        return None
    employee = db.get(Employee, employee_id)
    return employee.full_name if employee is not None else None


def to_brief(db: Session, snapshot: SchemaSnapshot) -> SnapshotBriefOut:
    return SnapshotBriefOut(
        id=snapshot.id,
        title=snapshot.title,
        comment=snapshot.comment,
        status=snapshot.status,
        created_at=snapshot.created_at,
        created_by=snapshot.created_by,
        created_by_name=_author_name(db, snapshot.created_by),
        published_at=snapshot.published_at,
        published_by=snapshot.published_by,
        published_by_name=_author_name(db, snapshot.published_by),
        counts=schema_graph.snapshot_counts(snapshot.payload or {}),
    )


def to_full(db: Session, snapshot: SchemaSnapshot) -> SnapshotOut:
    brief = to_brief(db, snapshot).model_dump()
    return SnapshotOut(**brief, payload=snapshot.payload or {})


def create_snapshot(
    db: Session, pit: Pit, payload: SnapshotCreate, *, actor: Employee
) -> SchemaSnapshot:
    """Зафиксировать текущее состояние схемы черновиком."""
    title = payload.title.strip()
    # Схема требует min_length=2 по сырой строке, поэтому «  » проходит Pydantic.
    # Проверяем уже обрезанное значение: пустое название снимка бессмысленно в списке.
    if len(title) < 2:
        raise ApiError(422, "schema_snapshot.title_empty", "Название снимка — минимум 2 символа")

    snapshot = SchemaSnapshot(
        id=uuid.uuid4(),
        pit_id=pit.id,
        title=title,
        comment=(payload.comment or "").strip() or None,
        status="draft",
        payload=schema_graph.build_snapshot_payload(db, pit),
        created_by=actor.id,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    counts = schema_graph.snapshot_counts(snapshot.payload)
    audit.add(
        "schema.snapshot_created",
        entity="schema_snapshot",
        entity_id=snapshot.id,
        detail=(
            f"Снимок схемы «{snapshot.title}»: "
            f"{counts['nodes']} объектов, {counts['edges']} связей, {counts['blocks']} блоков"
        ),
    )
    return snapshot


def list_snapshots(db: Session, pit: Pit, *, status: str | None = None) -> list[SchemaSnapshot]:
    stmt = select(SchemaSnapshot).where(SchemaSnapshot.pit_id == pit.id)
    if status:
        stmt = stmt.where(SchemaSnapshot.status == status)
    return list(db.scalars(stmt.order_by(SchemaSnapshot.created_at.desc())).all())


def latest_published_id(db: Session, pit: Pit) -> uuid.UUID | None:
    return db.scalar(
        select(SchemaSnapshot.id)
        .where(
            SchemaSnapshot.pit_id == pit.id,
            SchemaSnapshot.status == "published",
        )
        .order_by(SchemaSnapshot.published_at.desc())
        .limit(1)
    )


def get_snapshot(db: Session, pit: Pit, snapshot_id: uuid.UUID) -> SchemaSnapshot:
    snapshot = db.scalar(
        select(SchemaSnapshot).where(
            SchemaSnapshot.id == snapshot_id,
            SchemaSnapshot.pit_id == pit.id,
        )
    )
    if snapshot is None:
        raise not_found("Снимок схемы не найден")
    return snapshot


def publish_snapshot(db: Session, snapshot: SchemaSnapshot, *, actor: Employee) -> SchemaSnapshot:
    """Опубликовать версию. Повторная публикация того же снимка — конфликт."""
    if snapshot.status == "published":
        raise conflict("Снимок уже опубликован", "schema_snapshot.already_published")

    snapshot.status = "published"
    snapshot.published_by = actor.id
    snapshot.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(snapshot)

    audit.add(
        "schema.snapshot_published",
        entity="schema_snapshot",
        entity_id=snapshot.id,
        detail=f"Опубликована версия схемы «{snapshot.title}»",
    )
    return snapshot
