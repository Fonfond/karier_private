"""Модели домена."""

from app.models.audit import AuditLog
from app.models.auth import (
    AuthSession,
    Credential,
    Employee,
    MfaFactor,
    OnboardingToken,
    Permission,
    RecoveryCode,
    Role,
    role_permissions,
)
from app.models.base import Base
from app.models.documents import Document
from app.models.gis import Asset, AssetPort, AssetType, MapLayer, Pit, SchemaBlock, SchemaSnapshot
from app.models.ops import MaintenanceEntry, Defect, Inspection, InspectionItem, Media
from app.models.sync import AssetMove, ChangeLog, Conflict, SyncOp
from app.models.topology import Line, Link, SwitchingOp

__all__ = [
    "Base",
    "AuditLog",
    "AuthSession",
    "Credential",
    "Employee",
    "MfaFactor",
    "OnboardingToken",
    "Permission",
    "RecoveryCode",
    "Role",
    "role_permissions",
    "Pit",
    "SchemaBlock",
    "SchemaSnapshot",
    "MapLayer",
    "AssetType",
    "Asset",
    "AssetPort",
    "Line",
    "Link",
    "SwitchingOp",
    "Document",
    "MaintenanceEntry",
    "Inspection",
    "InspectionItem",
    "Defect",
    "Media",
    "ChangeLog",
    "SyncOp",
    "Conflict",
    "AssetMove",
]
