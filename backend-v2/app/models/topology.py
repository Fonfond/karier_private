"""Топология: логические линии, участки связей, журнал переключений."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin
from app.models.gis import SCHEMA


class Line(Base, TimestampMixin):
    """Логическая электрическая линия (фидер): «ф.21К», «ВЛ-6 кВ №4»."""

    __tablename__ = "lines"
    __table_args__ = (
        UniqueConstraint("pit_id", "code", name="uq_lines_pit_code"),
        CheckConstraint("kind in ('overhead','cable','busbar')", name="ck_lines_kind"),
        CheckConstraint(
            "state in ('energized','deenergized','grounded')", name="ck_lines_state"
        ),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey(f"{SCHEMA}.pits.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    kind = Column(String(16), nullable=False, default="cable")
    voltage_kv = Column(Numeric(6, 3))
    source_asset_id = Column(Uuid, ForeignKey(f"{SCHEMA}.assets.id", ondelete="SET NULL"))
    conductor_mark = Column(String(64))
    length_m = Column(Numeric(10, 2))
    state = Column(String(16), nullable=False, default="deenergized")
    status = Column(String(16), nullable=False, default="in_service")
    deleted_at = Column(DateTime(timezone=True))

    links = relationship("Link", back_populates="line")


class Link(Base, TimestampMixin):
    """Участок связи между портами двух объектов.

    `state` — положение коммутационного аппарата на участке:
    connected (включено), open (разомкнуто), grounded (заземлено).
    """

    __tablename__ = "links"
    __table_args__ = (
        CheckConstraint(
            "link_type in ('cable','overhead','busbar','jumper','internal')",
            name="ck_links_type",
        ),
        CheckConstraint("feed_role in ('main','reserve','backup')", name="ck_links_feed_role"),
        CheckConstraint("state in ('connected','open','grounded')", name="ck_links_state"),
        Index("ix_links_from", "from_port_id"),
        Index("ix_links_to", "to_port_id"),
        Index("ix_links_line", "line_id"),
        Index(
            "uq_links_pair_active",
            "from_port_id",
            "to_port_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey(f"{SCHEMA}.pits.id", ondelete="CASCADE"), nullable=False)
    from_port_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.asset_ports.id", ondelete="CASCADE"), nullable=False
    )
    to_port_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.asset_ports.id", ondelete="CASCADE"), nullable=False
    )
    line_id = Column(Uuid, ForeignKey(f"{SCHEMA}.lines.id", ondelete="SET NULL"))

    link_type = Column(String(16), nullable=False, default="cable")
    feed_role = Column(String(16), nullable=False, default="main")
    state = Column(String(16), nullable=False, default="connected")

    geometry = Column(JSONB, nullable=False, default=list)
    length_m = Column(Numeric(10, 2))
    cable_mark = Column(String(64))
    cross_section_mm2 = Column(Numeric(8, 2))
    cores = Column(Integer)
    attrs = Column(JSONB, nullable=False, default=dict)

    created_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    updated_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, default=1)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))

    from_port = relationship("AssetPort", foreign_keys=[from_port_id], lazy="joined")
    to_port = relationship("AssetPort", foreign_keys=[to_port_id], lazy="joined")
    line = relationship("Line", back_populates="links")


class SwitchingOp(Base):
    """Журнал переключений: кто, когда, что и почему изменил."""

    __tablename__ = "switching_ops"
    __table_args__ = (
        Index("ix_switching_asset", "asset_id", "performed_at"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey(f"{SCHEMA}.pits.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Uuid, ForeignKey(f"{SCHEMA}.assets.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(32), nullable=False)  # status_on|status_off|ground_on|ground_off
    from_state = Column(String(32))
    to_state = Column(String(32))
    reason = Column(String(255))
    performed_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    performed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note = Column(Text)

    asset = relationship("Asset", lazy="joined")
