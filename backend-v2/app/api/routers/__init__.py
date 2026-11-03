"""Роутеры API."""

from app.api.routers import (
    audit,
    auth,
    defects,
    documents,
    employees,
    gis,
    health,
    inspections,
    me,
    media,
)

__all__ = [
    "audit",
    "auth",
    "defects",
    "documents",
    "employees",
    "gis",
    "health",
    "inspections",
    "me",
    "media",
]
