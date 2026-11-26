"""Сервис аудита.

Записи собираются в контексте запроса и пишутся отдельной сессией БД после
формирования ответа. Это гарантирует, что отказ в доступе, неудачный вход и
откат бизнес-транзакции всё равно попадут в журнал.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


@dataclass
class PendingAudit:
    action: str
    entity: str | None = None
    entity_id: str | None = None
    result: str = "ok"
    detail: str | None = None
    payload: dict[str, Any] | None = None
    actor_id: uuid.UUID | None = None
    actor_tab_no: str | None = None
    actor_role: str | None = None


@dataclass
class AuditContext:
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    method: str | None = None
    path: str | None = None
    actor_id: uuid.UUID | None = None
    actor_tab_no: str | None = None
    actor_role: str | None = None
    # действия аварийной учётной записи помечаются в журнале отдельно
    break_glass: bool = False
    entries: list[PendingAudit] = field(default_factory=list)

    def set_actor(self, *, actor_id, tab_no: str, role: str, break_glass: bool = False) -> None:
        self.actor_id = actor_id
        self.actor_tab_no = tab_no
        self.actor_role = role
        self.break_glass = break_glass


_ctx: ContextVar[AuditContext | None] = ContextVar("audit_ctx", default=None)


def reset_context(**kwargs: Any) -> AuditContext:
    ctx = AuditContext(**kwargs)
    _ctx.set(ctx)
    return ctx


def get_context() -> AuditContext:
    ctx = _ctx.get()
    if ctx is None:  # вне HTTP-запроса (скрипты, тесты)
        ctx = AuditContext()
        _ctx.set(ctx)
    return ctx


def set_actor(*, actor_id, tab_no: str, role: str, break_glass: bool = False) -> None:
    get_context().set_actor(
        actor_id=actor_id, tab_no=tab_no, role=role, break_glass=break_glass
    )


def add(
    action: str,
    *,
    entity: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    result: str = "ok",
    detail: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
    actor_tab_no: str | None = None,
    actor_role: str | None = None,
) -> None:
    ctx = get_context()
    marked = dict(payload or {})
    if ctx.break_glass:
        marked["break_glass"] = True
    ctx.entries.append(
        PendingAudit(
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            result=result,
            detail=detail,
            payload=marked or None,
            actor_id=actor_id or ctx.actor_id,
            actor_tab_no=actor_tab_no or ctx.actor_tab_no,
            actor_role=actor_role or ctx.actor_role,
        )
    )


def flush(db: Session) -> int:
    """Записать накопленные события отдельной транзакцией."""
    ctx = _ctx.get()
    if ctx is None or not ctx.entries:
        return 0

    now = datetime.now(timezone.utc)
    rows = [
        AuditLog(
            at=now,
            actor_id=e.actor_id,
            actor_tab_no=e.actor_tab_no,
            actor_role=e.actor_role,
            action=e.action,
            entity=e.entity,
            entity_id=e.entity_id,
            result=e.result,
            ip=ctx.ip,
            user_agent=(ctx.user_agent or "")[:255] or None,
            request_id=ctx.request_id,
            method=ctx.method,
            path=(ctx.path or "")[:255] or None,
            detail=e.detail,
            payload=e.payload,
        )
        for e in ctx.entries
    ]
    db.add_all(rows)
    db.commit()
    count = len(rows)
    ctx.entries.clear()
    return count
