"""Зависимости FastAPI: БД, текущий пользователь, проверка прав."""

from __future__ import annotations

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ApiError, forbidden, unauthorized
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Employee
from app.services import audit
from app.services.auth import permissions_of

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Employee:
    if credentials is None or not credentials.credentials:
        raise unauthorized()

    try:
        payload = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "auth.token_expired", "Сессия истекла") from exc
    except Exception as exc:  # noqa: BLE001
        raise unauthorized("Недействительный токен") from exc

    employee = db.get(Employee, payload["sub"])
    if employee is None or employee.status != "active":
        raise unauthorized("Пользователь заблокирован или не найден")

    request.state.employee = employee
    request.state.session_id = payload.get("sid")
    audit.set_actor(
        actor_id=employee.id,
        tab_no=employee.tab_no,
        role=employee.role.code if employee.role else "",
    )
    return employee


def require_permission(code: str):
    def dependency(user: Employee = Depends(current_user)) -> Employee:
        if code not in permissions_of(user):
            audit.add(
                "perm.denied",
                entity="permission",
                entity_id=code,
                result="denied",
                detail=f"Роль {user.role.code if user.role else '-'} не имеет права {code}",
            )
            raise forbidden(f"Недостаточно прав: требуется «{code}»")
        return user

    return dependency


def require_admin(user: Employee = Depends(current_user)) -> Employee:
    """Только роль admin — для ручной раскладки схемы и управления учётками."""
    if user.role is None or user.role.code != "admin":
        audit.add(
            "perm.denied",
            entity="permission",
            entity_id="role:admin",
            result="denied",
            detail=f"Роль {user.role.code if user.role else '-'} не является администратором",
        )
        raise forbidden("Действие доступно только администратору")
    return user
