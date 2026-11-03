"""Базовый класс моделей и общие миксины.

Стиль объявления — классический `Column(...)`, а не `Mapped[...]`:
это снимает зависимость от разрешения аннотаций во время выполнения
(актуально для Python 3.14 и PEP 649) и одинаково работает во всех
поддерживаемых версиях SQLAlchemy 2.x.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
