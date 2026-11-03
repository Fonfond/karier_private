"""Роутеры API."""

from app.api.routers import audit, auth, documents, employees, gis, health, me

__all__ = ["audit", "auth", "documents", "employees", "gis", "health", "me"]
