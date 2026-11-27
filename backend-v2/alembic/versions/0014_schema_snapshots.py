"""Снимки однолинейной схемы: таблица версий топологии.

Revision ID: 0014_schema_snapshots
Revises: 0013_composite_types
Create Date: 2026-11-23

Снимок хранит полный слепок схемы (JSONB): узлы, порты, связи, блоки,
раскладку и штамп. Черновик (`draft`) — рабочая фиксация, `published` —
согласованная версия: публикация только проставляет автора и время,
сам слепок после публикации не меняется.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_schema_snapshots"
down_revision = "0013_composite_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('draft','published')", name="ck_schema_snapshots_status"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="gis",
        comment="Снимок схемы: состояние топологии на дату (черновик или опубликованная версия)",
    )
    op.create_index(
        "ix_schema_snapshots_pit_status",
        "schema_snapshots",
        ["pit_id", "status"],
        schema="gis",
    )
    op.create_index(
        "ix_schema_snapshots_created",
        "schema_snapshots",
        ["created_at"],
        schema="gis",
    )


def downgrade() -> None:
    op.drop_index("ix_schema_snapshots_created", table_name="schema_snapshots", schema="gis")
    op.drop_index("ix_schema_snapshots_pit_status", table_name="schema_snapshots", schema="gis")
    op.drop_table("schema_snapshots", schema="gis")
