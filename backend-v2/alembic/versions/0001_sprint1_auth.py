"""Спринт 1: доступ, роли и аудит.

Создаёт схемы `auth` и `audit`, таблицы сотрудников, паролей, 2FA, сессий,
одноразовых кодов регистрации и неизменяемый журнал действий.

Важно: схема `public` с таблицами прототипа (users/equipment/…) не затрагивается —
новая система живёт в собственных схемах той же базы.

Revision ID: 0001_sprint1_auth
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_sprint1_auth"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    # --- журнал аудита ----------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_tab_no", sa.String(length=16), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=48), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
        comment="Журнал действий: только вставка, изменение и удаление запрещены триггером",
    )
    op.create_index("ix_audit_at", "audit_log", ["at"], schema="audit")
    op.create_index("ix_audit_actor", "audit_log", ["actor_id", "at"], schema="audit")
    op.create_index("ix_audit_entity", "audit_log", ["entity", "entity_id", "at"], schema="audit")

    # --- справочники доступа ---------------------------------------------
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
        schema="auth",
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        schema="auth",
    )

    # --- сотрудники -------------------------------------------------------
    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tab_no", sa.String(length=16), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=128), nullable=True),
        sa.Column("department", sa.String(length=128), nullable=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("otp_channel", sa.String(length=16), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("access_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('active','blocked','dismissed')", name="ck_employees_status"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["role_id"], ["auth.roles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tab_no", name="uq_employees_tab_no"),
        schema="auth",
        comment="Сотрудник = разрешённый табельный номер (закрытая регистрация)",
    )
    op.create_index("ix_employees_role_status", "employees", ["role_id", "status"], schema="auth")

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["auth.permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["auth.roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
        schema="auth",
    )

    # --- учётные данные ---------------------------------------------------
    op.create_table(
        "credentials",
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("password_algo", sa.String(length=32), nullable=False),
        sa.Column("password_updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("must_change", sa.Boolean(), nullable=False),
        sa.Column("failed_attempts", sa.SmallInteger(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("employee_id"),
        schema="auth",
        comment="Хэш пароля (Argon2id) и состояние блокировки",
    )
    op.create_table(
        "mfa_factors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_counter", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind in ('totp','webauthn','telegram')", name="ck_mfa_kind"),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
        comment="Второй фактор; секрет TOTP зашифрован AES-256-GCM",
    )
    op.create_index("ix_mfa_factors_employee", "mfa_factors", ["employee_id"], schema="auth")

    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
    )
    op.create_index("ix_recovery_codes_employee", "recovery_codes", ["employee_id"], schema="auth")

    # --- сессии и регистрация ---------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_hash", sa.String(length=128), nullable=False),
        sa.Column("prev_refresh_hash", sa.String(length=128), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_hash", name="uq_sessions_refresh_hash"),
        schema="auth",
        comment="Сессия устройства; refresh-токен хранится хэшем, prev_refresh_hash ловит повторное использование",
    )
    op.create_index("ix_sessions_employee", "sessions", ["employee_id", "revoked_at"], schema="auth")
    op.create_index("ix_sessions_family", "sessions", ["family_id"], schema="auth")

    op.create_table(
        "onboarding_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
    )
    op.create_index("ix_onboarding_employee", "onboarding_tokens", ["employee_id", "consumed_at"], schema="auth")

    # --- защита журнала от изменения --------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit.forbid_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % запрещён', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update
        BEFORE UPDATE OR DELETE ON audit.audit_log
        FOR EACH ROW EXECUTE FUNCTION audit.forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit.audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit.forbid_mutation()")

    op.drop_index("ix_onboarding_employee", table_name="onboarding_tokens", schema="auth")
    op.drop_table("onboarding_tokens", schema="auth")
    op.drop_index("ix_sessions_family", table_name="sessions", schema="auth")
    op.drop_index("ix_sessions_employee", table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
    op.drop_index("ix_recovery_codes_employee", table_name="recovery_codes", schema="auth")
    op.drop_table("recovery_codes", schema="auth")
    op.drop_index("ix_mfa_factors_employee", table_name="mfa_factors", schema="auth")
    op.drop_table("mfa_factors", schema="auth")
    op.drop_table("credentials", schema="auth")
    op.drop_table("role_permissions", schema="auth")
    op.drop_index("ix_employees_role_status", table_name="employees", schema="auth")
    op.drop_table("employees", schema="auth")
    op.drop_table("roles", schema="auth")
    op.drop_table("permissions", schema="auth")
    op.drop_index("ix_audit_entity", table_name="audit_log", schema="audit")
    op.drop_index("ix_audit_actor", table_name="audit_log", schema="audit")
    op.drop_index("ix_audit_at", table_name="audit_log", schema="audit")
    op.drop_table("audit_log", schema="audit")

    op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE")
