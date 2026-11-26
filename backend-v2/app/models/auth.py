"""Модели домена auth: сотрудники, роли, доступ, 2FA, сессии."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin

SCHEMA = "auth"

# --- роли и права ----------------------------------------------------------

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Uuid, ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        Uuid,
        ForeignKey(f"{SCHEMA}.permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema=SCHEMA,
)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_roles_code"), {"schema": SCHEMA})

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    code = Column(String(32), nullable=False)  # admin | operator | viewer | contractor
    name = Column(String(128), nullable=False)
    description = Column(Text)
    is_system = Column(Boolean, nullable=False, default=True)

    permissions = relationship(
        "Permission", secondary=role_permissions, back_populates="roles", lazy="selectin"
    )
    employees = relationship("Employee", back_populates="role")


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_permissions_code"), {"schema": SCHEMA})

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    code = Column(String(64), nullable=False)
    description = Column(String(255))

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")


# --- сотрудники ------------------------------------------------------------

class Employee(Base, TimestampMixin):
    """Карточка сотрудника. Табельный номер — логин и «пропуск» в систему:
    завести карточку может только администратор, поэтому регистрация закрытая."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("tab_no", name="uq_employees_tab_no"),
        CheckConstraint(
            "status in ('active','blocked','dismissed')", name="ck_employees_status"
        ),
        Index("ix_employees_role_status", "role_id", "status"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tab_no = Column(String(16), nullable=False)
    full_name = Column(String(255), nullable=False)
    position = Column(String(128))
    department = Column(String(128))

    phone_e164 = Column(String(20))
    email = Column(String(255))
    telegram_id = Column(BigInteger)
    otp_channel = Column(String(16), nullable=False, default="telegram")  # telegram|email|manual

    role_id = Column(Uuid, ForeignKey(f"{SCHEMA}.roles.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    # аварийная учётная запись: защищена от удаления через интерфейс
    is_break_glass = Column(Boolean, nullable=False, default=False, server_default="false")
    access_until = Column(DateTime(timezone=True))
    dismissed_at = Column(DateTime(timezone=True))

    created_by = Column(Uuid, ForeignKey(f"{SCHEMA}.employees.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, default=1)

    role = relationship("Role", back_populates="employees", lazy="joined")
    # Дочерние строки удаляются каскадом в БД (ON DELETE CASCADE). Без passive_deletes
    # SQLAlchemy пытается обнулить их FK перед удалением родителя и падает на NOT NULL.
    credential = relationship(
        "Credential",
        back_populates="employee",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mfa_factors = relationship(
        "MfaFactor",
        back_populates="employee",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions = relationship(
        "AuthSession",
        back_populates="employee",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class Credential(Base):
    """Пароль и состояние блокировки. Пароль хранится только здесь (Argon2id)."""

    __tablename__ = "credentials"
    __table_args__ = ({"schema": SCHEMA},)

    employee_id = Column(
        Uuid,
        ForeignKey(f"{SCHEMA}.employees.id", ondelete="CASCADE"),
        primary_key=True,
    )
    password_hash = Column(String(255), nullable=False)
    password_algo = Column(String(32), nullable=False, default="argon2id")
    password_updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    must_change = Column(Boolean, nullable=False, default=False)
    failed_attempts = Column(SmallInteger, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    last_login_at = Column(DateTime(timezone=True))

    employee = relationship("Employee", back_populates="credential")


class MfaFactor(Base):
    """Второй фактор. Для TOTP секрет шифруется AES-256-GCM."""

    __tablename__ = "mfa_factors"
    __table_args__ = (
        CheckConstraint("kind in ('totp','webauthn','telegram')", name="ck_mfa_kind"),
        Index("ix_mfa_factors_employee", "employee_id"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.employees.id", ondelete="CASCADE"), nullable=False
    )
    kind = Column(String(16), nullable=False, default="totp")
    label = Column(String(64), default="Аутентификатор")
    secret_enc = Column(LargeBinary, nullable=False)
    confirmed_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))
    last_counter = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at = Column(DateTime(timezone=True))

    employee = relationship("Employee", back_populates="mfa_factors")


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"
    __table_args__ = (
        Index("ix_recovery_codes_employee", "employee_id"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.employees.id", ondelete="CASCADE"), nullable=False
    )
    code_hash = Column(String(255), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuthSession(Base):
    """Сессия устройства. refresh-токен хранится хэшем, при ротации заменяется."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("refresh_hash", name="uq_sessions_refresh_hash"),
        Index("ix_sessions_employee", "employee_id", "revoked_at"),
        Index("ix_sessions_family", "family_id"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.employees.id", ondelete="CASCADE"), nullable=False
    )
    family_id = Column(Uuid, nullable=False, default=uuid.uuid4)
    refresh_hash = Column(String(128), nullable=False)
    # предыдущий хэш нужен, чтобы распознать повторное использование
    # уже ротированного refresh-токена (признак кражи) и отозвать семейство
    prev_refresh_hash = Column(String(128))
    refresh_expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    revoke_reason = Column(String(64))
    ip = Column(String(64))
    user_agent = Column(String(255))
    app_version = Column(String(32))

    employee = relationship("Employee", back_populates="sessions")


class OnboardingToken(Base):
    """Одноразовый код первичной регистрации (закрытая регистрация)."""

    __tablename__ = "onboarding_tokens"
    __table_args__ = (
        Index("ix_onboarding_employee", "employee_id", "consumed_at"),
        {"schema": SCHEMA},
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id = Column(
        Uuid, ForeignKey(f"{SCHEMA}.employees.id", ondelete="CASCADE"), nullable=False
    )
    channel = Column(String(16), nullable=False)  # telegram|email|manual
    code_hash = Column(String(255), nullable=False)
    attempts = Column(SmallInteger, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(Uuid, ForeignKey(f"{SCHEMA}.employees.id", ondelete="SET NULL"))
