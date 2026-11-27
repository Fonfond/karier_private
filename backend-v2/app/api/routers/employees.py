"""Администрирование сотрудников (только роль admin / право employee.manage)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_permission
from app.core.errors import ApiError, conflict, not_found
from app.core.security import validate_password_policy
from app.db.session import get_db
from app.models import Credential, Employee, MfaFactor, Role
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeListOut,
    EmployeeOut,
    EmployeeUpdate,
    InviteOut,
    OtpIssueOut,
    ResetPasswordOut,
)
from app.services import audit
from app.services.auth import (
    issue_registration_code,
    mfa_factor,
    normalize_tab,
    set_temp_password,
    start_registration,
)

router = APIRouter(prefix="/employees", tags=["employees"])

Permission = Depends(require_permission("employee.manage"))


def _serialize(db: Session, employee: Employee) -> EmployeeOut:
    return EmployeeOut(
        id=employee.id,
        tab_no=employee.tab_no,
        full_name=employee.full_name,
        position=employee.position,
        department=employee.department,
        phone_e164=employee.phone_e164,
        email=employee.email,
        telegram_id=employee.telegram_id,
        otp_channel=employee.otp_channel,
        role=employee.role.code if employee.role else "",
        status=employee.status,
        is_break_glass=bool(employee.is_break_glass),
        access_until=employee.access_until,
        has_credentials=employee.credential is not None,
        mfa_enabled=mfa_factor(db, employee.id) is not None,
        last_login_at=employee.credential.last_login_at if employee.credential else None,
        created_at=employee.created_at,
    )


def _get_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise not_found("Сотрудник не найден")
    return employee


def _role_or_400(db: Session, code: str) -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise ApiError(400, "validation.failed", f"Неизвестная роль: {code}")
    return role


@router.get("", response_model=EmployeeListOut, summary="Список сотрудников")
def list_employees(
    search: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, pattern="^(active|blocked|dismissed)$"),
    role: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeListOut:
    stmt = select(Employee)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Employee.full_name.ilike(needle), Employee.tab_no.ilike(needle))
        )
    if status:
        stmt = stmt.where(Employee.status == status)
    if role:
        stmt = stmt.join(Role).where(Role.code == role)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Employee.tab_no).limit(limit).offset(offset)
    ).unique().all()
    return EmployeeListOut(items=[_serialize(db, e) for e in rows], total=total)


@router.post("", response_model=EmployeeOut, status_code=201, summary="Завести сотрудника")
def create_employee(
    payload: EmployeeCreate,
    admin: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    tab_no = normalize_tab(payload.tab_no)
    if db.scalar(select(Employee).where(Employee.tab_no == tab_no)) is not None:
        raise conflict("Сотрудник с таким табельным номером уже существует", "employee.duplicate_tab")

    role = _role_or_400(db, payload.role)
    employee = Employee(
        id=uuid.uuid4(),
        tab_no=tab_no,
        full_name=payload.full_name.strip(),
        position=payload.position,
        department=payload.department,
        phone_e164=payload.phone_e164,
        email=payload.email,
        telegram_id=payload.telegram_id,
        otp_channel=payload.otp_channel,
        role_id=role.id,
        status="active",
        access_until=payload.access_until,
        created_by=admin.id,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    audit.add(
        "employee.created",
        entity="employee",
        entity_id=employee.id,
        detail=f"Заведён сотрудник {employee.tab_no} ({role.code})",
        payload={"tab_no": employee.tab_no, "role": role.code},
    )
    return _serialize(db, employee)


@router.get("/{employee_id}", response_model=EmployeeOut, summary="Карточка сотрудника")
def get_employee(
    employee_id: uuid.UUID,
    _: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    return _serialize(db, _get_or_404(db, employee_id))


@router.patch("/{employee_id}", response_model=EmployeeOut, summary="Изменить сотрудника")
def update_employee(
    employee_id: uuid.UUID,
    payload: EmployeeUpdate,
    admin: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = _get_or_404(db, employee_id)
    if employee.is_break_glass:
        raise ApiError(
            400,
            "employee.break_glass_protected",
            "Аварийная учётная запись защищена: используйте reset_break_glass.py",
        )
    before = {
        "full_name": employee.full_name,
        "role": employee.role.code if employee.role else None,
        "position": employee.position,
    }

    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"]:
        employee.role_id = _role_or_400(db, data.pop("role")).id
    data.pop("role", None)
    for field, value in data.items():
        setattr(employee, field, value)
    employee.version = (employee.version or 1) + 1
    db.commit()
    db.refresh(employee)

    audit.add(
        "employee.updated",
        entity="employee",
        entity_id=employee.id,
        detail="Изменена карточка сотрудника",
        payload={"before": before, "after": payload.model_dump(exclude_unset=True)},
    )
    return _serialize(db, employee)


@router.delete(
    "/{employee_id}",
    response_model=EmployeeOut,
    summary="Уволить сотрудника (архивировать учётную запись)",
)
def dismiss_employee(
    employee_id: uuid.UUID,
    admin: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = _get_or_404(db, employee_id)
    if employee.is_break_glass:
        raise ApiError(
            400,
            "employee.break_glass_protected",
            "Аварийная учётная запись защищена: используйте reset_break_glass.py",
        )
    if employee.id == admin.id:
        raise ApiError(400, "employee.self_action", "Нельзя уволить самого себя")

    if employee.role is not None and employee.role.code == "admin":
        active_admins = db.scalar(
            select(func.count(Employee.id))
            .join(Role, Employee.role_id == Role.id)
            .where(Role.code == "admin", Employee.status == "active")
        ) or 0
        if active_admins <= 1:
            raise conflict(
                "Нельзя уволить последнего администратора", "employee.last_admin"
            )

    employee.status = "dismissed"
    db.commit()
    from app.services.auth import revoke_all_sessions

    revoked = revoke_all_sessions(db, employee, reason="employee_dismissed")
    audit.add(
        "employee.dismissed",
        entity="employee",
        entity_id=employee.id,
        detail=f"Сотрудник {employee.tab_no} уволен, отозвано сессий: {revoked}",
    )
    return _serialize(db, employee)


@router.delete(
    "/{employee_id}/permanent",
    response_model=EmployeeOut,
    summary="Удалить сотрудника навсегда (только без истории)",
)
def delete_employee_permanently(
    employee_id: uuid.UUID,
    admin: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = _get_or_404(db, employee_id)
    if employee.is_break_glass:
        raise ApiError(
            400,
            "employee.break_glass_protected",
            "Аварийная учётная запись защищена: используйте reset_break_glass.py",
        )
    if employee.id == admin.id:
        raise ApiError(400, "employee.self_action", "Нельзя удалить самого себя")

    if employee.role is not None and employee.role.code == "admin":
        active_admins = db.scalar(
            select(func.count(Employee.id))
            .join(Role, Employee.role_id == Role.id)
            .where(Role.code == "admin", Employee.status == "active")
        ) or 0
        if active_admins <= 1:
            raise conflict("Нельзя удалить последнего администратора", "employee.last_admin")

    from app.models import AuditLog

    actions = db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.actor_id == employee.id)
    ) or 0
    if actions:
        raise conflict(
            f"У сотрудника есть история действий в журнале ({actions}). "
            "Удаление стёрло бы авторство — используйте «Уволить»",
            "employee.has_history",
        )

    payload = {"tab_no": employee.tab_no, "full_name": employee.full_name}
    created_at = employee.created_at
    from app.services.auth import revoke_all_sessions

    revoke_all_sessions(db, employee, reason="employee_deleted")
    audit.add(
        "employee.deleted",
        entity="employee",
        entity_id=employee.id,
        detail=f"Сотрудник {employee.tab_no} удалён навсегда",
        payload=payload,
    )
    db.delete(employee)
    db.commit()

    return EmployeeOut(
        id=employee_id,
        tab_no=payload["tab_no"],
        full_name=payload["full_name"],
        position=None,
        department=None,
        phone_e164=None,
        email=None,
        telegram_id=None,
        otp_channel="manual",
        role="",
        status="deleted",
        access_until=None,
        has_credentials=False,
        mfa_enabled=False,
        last_login_at=None,
        created_at=created_at,
    )


@router.post("/{employee_id}/block", response_model=EmployeeOut, summary="Заблокировать")
def block_employee(
    employee_id: uuid.UUID,
    admin: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = _get_or_404(db, employee_id)
    if employee.is_break_glass:
        raise ApiError(
            400,
            "employee.break_glass_protected",
            "Аварийная учётная запись защищена: используйте reset_break_glass.py",
        )
    if employee.id == admin.id:
        raise ApiError(400, "employee.self_action", "Нельзя заблокировать самого себя")

    employee.status = "blocked"
    db.commit()
    from app.services.auth import revoke_all_sessions

    revoked = revoke_all_sessions(db, employee, reason="employee_blocked")
    audit.add(
        "employee.blocked",
        entity="employee",
        entity_id=employee.id,
        detail=f"Заблокирован, отозвано сессий: {revoked}",
    )
    return _serialize(db, employee)


@router.post("/{employee_id}/unblock", response_model=EmployeeOut, summary="Разблокировать")
def unblock_employee(
    employee_id: uuid.UUID,
    _: Employee = Permission,
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = _get_or_404(db, employee_id)
    employee.status = "active"
    if employee.credential is not None:
        employee.credential.failed_attempts = 0
        employee.credential.locked_until = None
    db.commit()
    audit.add("employee.unblocked", entity="employee", entity_id=employee.id, detail="Разблокирован")
    return _serialize(db, employee)


@router.post(
    "/{employee_id}/reset-password",
    response_model=ResetPasswordOut,
    summary="Сбросить пароль (выдаётся временный)",
)
def reset_password(
    employee_id: uuid.UUID,
    _: Employee = Permission,
    db: Session = Depends(get_db),
) -> ResetPasswordOut:
    employee = _get_or_404(db, employee_id)
    temp = set_temp_password(db, employee)
    return ResetPasswordOut(temp_password=temp)


@router.post(
    "/{employee_id}/otp",
    response_model=OtpIssueOut,
    status_code=201,
    summary="Выдать код первичной регистрации (одноразовый, 10 минут)",
)
def issue_otp(
    employee_id: uuid.UUID,
    _: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OtpIssueOut:
    """Код возвращается администратору один раз; в БД хранится только хеш."""
    employee = _get_or_404(db, employee_id)
    data = issue_registration_code(db, employee)
    return OtpIssueOut(**data)


@router.post(
    "/{employee_id}/resend-invite",
    response_model=InviteOut,
    summary="Статус кода первичной регистрации (сам код не возвращается)",
)
def resend_invite(
    employee_id: uuid.UUID,
    _: Employee = Permission,
    db: Session = Depends(get_db),
) -> InviteOut:
    """Контракт S-5: код не выдаётся и не возвращается.

    Живой код выдаёт администратор через `POST /{id}/otp` (и видит его один раз).
    Здесь — только состояние: есть ли действующий код и сколько ему осталось.
    """
    employee = _get_or_404(db, employee_id)
    if employee.credential is not None:
        raise conflict("Сотрудник уже зарегистрирован", "employee.already_registered")
    state = start_registration(db, employee.tab_no)
    return InviteOut(
        delivery=state["delivery"],
        expires_in=state["expires_in"],
        issued=state["expires_in"] > 0,
    )
