"""Журнал действий (append-only).

Таблица защищена триггером в миграции: UPDATE и DELETE запрещены на уровне БД.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base

SCHEMA = "audit"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_at", "at"),
        Index("ix_audit_actor", "actor_id", "at"),
        Index("ix_audit_entity", "entity", "entity_id", "at"),
        {"schema": SCHEMA},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    actor_id = Column(Uuid)
    actor_tab_no = Column(String(16))
    actor_role = Column(String(32))

    action = Column(String(64), nullable=False)
    entity = Column(String(48))
    entity_id = Column(String(64))
    result = Column(String(16), nullable=False, default="ok")  # ok|denied|error

    ip = Column(String(64))
    user_agent = Column(String(255))
    request_id = Column(String(36))
    method = Column(String(8))
    path = Column(String(255))

    detail = Column(Text)
    payload = Column(JSONB)
