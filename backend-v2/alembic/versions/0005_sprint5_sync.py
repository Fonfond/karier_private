"""Спринт 5: журнал изменений, идемпотентность, конфликты, перемещения.

Создаёт `ops.change_log`, `ops.sync_ops`, `ops.conflicts`, `gis.asset_moves`
и триггеры, которые пишут в журнал при изменении объектов, связей и дефектов.

Revision ID: 0005_sprint5_sync
Revises: 0004_sprint4_ops
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_sprint5_sync"
down_revision: str | None = "0004_sprint4_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "change_log",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("op", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("client_ts", sa.DateTime(timezone=True)),
        sa.Column("server_ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("pit_id", sa.Uuid()),
        sa.PrimaryKeyConstraint("seq"),
        schema="ops",
        comment="Лента изменений для pull-синхронизации (пишется триггерами)",
    )
    op.create_index("ix_change_log_entity", "change_log", ["entity", "entity_id", "seq"], schema="ops")
    op.create_index("ix_change_log_pit", "change_log", ["pit_id", "seq"], schema="ops")

    op.create_table(
        "sync_ops",
        sa.Column("op_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=64)),
        sa.Column("employee_id", sa.Uuid()),
        sa.Column("entity", sa.String(length=32)),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("op_id"),
        schema="ops",
        comment="Ключи идемпотентности принятых операций",
    )

    op.create_table(
        "conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid()),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("winner", sa.String(length=16), nullable=False),
        sa.Column("winner_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("loser_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("client_ts", sa.DateTime(timezone=True)),
        sa.Column("server_ts", sa.DateTime(timezone=True)),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("note", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
        comment="Конфликты версий: победитель и проигравшее изменение",
    )
    op.create_index("ix_conflicts_entity", "conflicts", ["entity", "entity_id", "created_at"], schema="ops")

    op.create_table(
        "asset_moves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("from_x", sa.Numeric(precision=12, scale=2)),
        sa.Column("from_y", sa.Numeric(precision=12, scale=2)),
        sa.Column("to_x", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("to_y", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("moved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("moved_by", sa.Uuid()),
        sa.Column("note", sa.String(length=255)),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("media_id", sa.Uuid()),
        sa.Column("client_ts", sa.DateTime(timezone=True)),
        sa.Column("conflict", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["gis.assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["ops.media.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["moved_by"], ["auth.employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pit_id"], ["gis.pits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="gis",
        comment="История перемещений мобильных объектов",
    )
    op.create_index("ix_asset_moves_asset", "asset_moves", ["asset_id", "moved_at"], schema="gis")

    # --- триггеры журнала изменений --------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.log_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_actor uuid;
            v_pit uuid;
            v_entity text := TG_ARGV[0];
        BEGIN
            BEGIN
                v_actor := nullif(current_setting('karier.actor_id', true), '')::uuid;
            EXCEPTION WHEN others THEN
                v_actor := NULL;
            END;

            IF TG_OP = 'DELETE' THEN
                v_pit := OLD.pit_id;
                INSERT INTO ops.change_log (entity, entity_id, op, payload, actor_id, pit_id)
                VALUES (v_entity, OLD.id, 'delete', to_jsonb(OLD), v_actor, v_pit);
                RETURN OLD;
            END IF;

            v_pit := NEW.pit_id;
            INSERT INTO ops.change_log (entity, entity_id, op, payload, actor_id, pit_id)
            VALUES (v_entity, NEW.id, lower(TG_OP), to_jsonb(NEW), v_actor, v_pit);
            RETURN NEW;
        END;
        $$;
        """
    )
    for table, entity in (
        ("gis.assets", "asset"),
        ("gis.links", "link"),
        ("ops.defects", "defect"),
    ):
        op.execute(
            f"CREATE TRIGGER {table.split('.')[1]}_change_log "
            f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION ops.log_change('{entity}')"
        )


def downgrade() -> None:
    for table in ("assets", "links"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_change_log ON gis.{table}")
    op.execute("DROP TRIGGER IF EXISTS defects_change_log ON ops.defects")
    op.execute("DROP FUNCTION IF EXISTS ops.log_change()")

    op.drop_index("ix_asset_moves_asset", table_name="asset_moves", schema="gis")
    op.drop_table("asset_moves", schema="gis")
    op.drop_index("ix_conflicts_entity", table_name="conflicts", schema="ops")
    op.drop_table("conflicts", schema="ops")
    op.drop_table("sync_ops", schema="ops")
    op.drop_index("ix_change_log_pit", table_name="change_log", schema="ops")
    op.drop_index("ix_change_log_entity", table_name="change_log", schema="ops")
    op.drop_table("change_log", schema="ops")
