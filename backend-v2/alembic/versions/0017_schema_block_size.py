"""Этап 3: размер блока схемы — ``gis.assets.schema_width`` / ``schema_height``.

Revision ID: 0017_schema_block_size
Revises: 0016_stage2_equipment
Create Date: 2026-11-27

Миграция только добавляет (ни одна таблица/колонка/строка не удаляется):

1. ``gis.assets.schema_width`` и ``gis.assets.schema_height`` — размер блока
   однолинейной схемы (ПС, БКРУ, КТП, контур) в пикселях холста. Nullable:
   у одиночных символов и ячеек размера нет, их рисует клиент по символу.
2. CHECK ``ck_assets_schema_*_positive`` — размер, если задан, строго больше
   нуля (0 и отрицательные ломают NodeResizer и подписи блока).
3. Разовая досыпка (backfill) размеров контуров, которые до этапа 3 хранились
   только в ``attrs.contour_w`` / ``attrs.contour_h``: колонки становятся
   единственным источником правды для редактора, а JSONB-ключи остаются ради
   обратной совместимости старых клиентов/отчётов. Досыпка идёт только в
   пустые колонки (``IS NULL``) и только для положительных числовых значений,
   поэтому данные админа не перезаписываются.

Координаты ячеек внутри блока уже хранятся в ``gis.assets.schema_local_x`` /
``schema_local_y`` (миграция 0011) — эта миграция их не дублирует и не меняет:
новых ``schema_cell_x/y`` нет.

Обратная совместимость: колонки nullable, старые API читают ``attrs`` как раньше
(``GET /api/topology/graph`` отдаёт ширину из колонки, а при её отсутствии — из
``attrs.contour_w``). Откат удаляет только эти две колонки и их CHECK-и; размеры
контуров остаются в ``attrs``, объекты и связи не затрагиваются.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_schema_block_size"
down_revision: str | None = "0016_stage2_equipment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Верхняя граница разумного размера блока на холсте (px): защищает от опечаток
#: вроде «360000» и от переполнения Numeric(10, 2) при досыпке.
MAX_BLOCK_SIZE = 99_999_999

#: Размеры контуров до этапа 3 жили только здесь (см. services/schema_blocks.py).
BACKFILL_SQL = f"""
UPDATE gis.assets
   SET schema_width = round((attrs ->> 'contour_w')::numeric, 2),
       schema_height = round((attrs ->> 'contour_h')::numeric, 2)
 WHERE schema_width IS NULL
   AND schema_height IS NULL
   AND jsonb_typeof(attrs -> 'contour_w') = 'number'
   AND jsonb_typeof(attrs -> 'contour_h') = 'number'
   AND (attrs ->> 'contour_w')::numeric > 0
   AND (attrs ->> 'contour_h')::numeric > 0
   AND (attrs ->> 'contour_w')::numeric <= {MAX_BLOCK_SIZE}
   AND (attrs ->> 'contour_h')::numeric <= {MAX_BLOCK_SIZE}
"""


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("schema_width", sa.Numeric(10, 2), nullable=True),
        schema="gis",
    )
    op.add_column(
        "assets",
        sa.Column("schema_height", sa.Numeric(10, 2), nullable=True),
        schema="gis",
    )
    op.create_check_constraint(
        "ck_assets_schema_width_positive",
        "assets",
        "schema_width is null or schema_width > 0",
        schema="gis",
    )
    op.create_check_constraint(
        "ck_assets_schema_height_positive",
        "assets",
        "schema_height is null or schema_height > 0",
        schema="gis",
    )
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.drop_constraint("ck_assets_schema_height_positive", "assets", schema="gis")
    op.drop_constraint("ck_assets_schema_width_positive", "assets", schema="gis")
    op.drop_column("assets", "schema_height", schema="gis")
    op.drop_column("assets", "schema_width", schema="gis")
