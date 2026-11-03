"""Документы объекта: электросхемы, уставки, инструкции."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.models.base import Base

SCHEMA = "ops"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type in ('schematic','settings','manual','other')", name="ck_documents_type"
        ),
        Index("ix_documents_asset", "asset_id", "created_at"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    pit_id = Column(Uuid, ForeignKey("gis.pits.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Uuid, ForeignKey("gis.assets.id", ondelete="CASCADE"), nullable=False)

    doc_type = Column(String(16), nullable=False, default="other")
    title = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    mime = Column(String(128), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    storage_path = Column(String(500), nullable=False)
    sha256 = Column(String(64))
    version = Column(String(32))

    uploaded_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Uuid, ForeignKey("auth.employees.id", ondelete="SET NULL"))

    asset = relationship("Asset", lazy="joined")
