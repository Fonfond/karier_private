"""Синхронизация: журнал изменений, идемпотентность, конфликты, перемещения."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base

SCHEMA = "ops"


class ChangeLog(Base):
    """Лента изменений для pull-синхронизации. Пишется триггерами БД."""

    __tablename__ = "change_log"
    __table_args__ = (
        Index("ix_change_log_entity", "entity", "entity_id", "seq"),
        Index("ix_change_log_pit", "pit_id", "seq"),
        {"schema": SCHEMA},
    )

    seq = Column(BigInteger, primary_key=True, autoincrement=True)
    entity = Column(String(32), nullable=False)
    entity_id = Column(Uuid, nullable=False)
    op = Column(String(16), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    actor_id = Column(Uuid)
    client_ts = Column(DateTime(timezone=True))
    server_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    pit_id = Column(Uuid)


class SyncOp(Base):
    """Принятые операции: ключ идемпотентности для повторной отправки пачки."""

    __tablename__ = "sync_ops"
    __table_args__ = ({"schema": SCHEMA},)

    op_id = Column(Uuid, primary_key=True)
    device_id = Column(String(64))
    employee_id = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    entity = Column(String(32))
    entity_id = Column(Uuid)
    status = Column(String(24), nullable=False, default="applied")
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Conflict(Base):
    """Зафиксированный конфликт версий: кто победил и что было у проигравшего."""

    __tablename__ = "conflicts"
    __table_args__ = (
        Index("ix_conflicts_entity", "entity", "entity_id", "created_at"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey("gis.pits.id", ondelete="CASCADE"))
    entity = Column(String(32), nullable=False)
    entity_id = Column(Uuid, nullable=False)
    kind = Column(String(32), nullable=False, default="version_mismatch")
    winner = Column(String(16), nullable=False, default="server")
    winner_payload = Column(JSONB, nullable=False, default=dict)
    loser_payload = Column(JSONB, nullable=False, default=dict)
    client_ts = Column(DateTime(timezone=True))
    server_ts = Column(DateTime(timezone=True))
    actor_id = Column(Uuid)
    note = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssetMove(Base):
    """История перемещений мобильного объекта («кукушки»)."""

    __tablename__ = "asset_moves"
    __table_args__ = (
        Index("ix_asset_moves_asset", "asset_id", "moved_at"),
        {"schema": "gis"},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey("gis.pits.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Uuid, ForeignKey("gis.assets.id", ondelete="CASCADE"), nullable=False)
    from_x = Column(Numeric(12, 2))
    from_y = Column(Numeric(12, 2))
    to_x = Column(Numeric(12, 2), nullable=False)
    to_y = Column(Numeric(12, 2), nullable=False)
    moved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    moved_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    note = Column(String(255))
    source = Column(String(16), nullable=False, default="online")
    media_id = Column(Uuid, ForeignKey("ops.media.id", ondelete="SET NULL"))
    client_ts = Column(DateTime(timezone=True))
    conflict = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    asset = relationship("Asset", lazy="joined")
