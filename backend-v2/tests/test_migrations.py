"""Проверка миграций Alembic на отдельной пустой базе (S-3).

Что проверяем:

1. `alembic heads` — ровно одна голова (защита от случайного второго head при мёрже).
2. Полный цикл на пустой БД: ``upgrade head`` → ``downgrade base`` → ``upgrade head``.
   Если downgrade сломан (или его вообще нет), тест падает — именно это ловит
   «миграция накатывается, а откатиться не может».
3. ``autogenerate`` на свежей схеме: новых расхождений моделей и БД быть не должно.
   Известный baseline-дрейф перечислен в ``KNOWN_*`` ниже и зафиксирован 2026-11-25
   (проверка V1): ``docs/team/11-v1-acceptance.md`` §6 и ``docs/team/13-r2-review.md``
   (оговорка C1). Это 29 предсуществующих операций: 4 индекса, которые есть в БД,
   но не объявлены в моделях; 2 внешних ключа, объявленных только в моделях;
   23 комментария таблиц, которые заданы миграциями, но не моделями.
   Пустой autogenerate глобально в этом спринте НЕ требуется — это задача S-10:
   тест сравнивает результат с baseline и падает только на НОВЫХ расхождениях
   (а также если часть baseline исчезла — значит список пора обновить, порядок
   обновления описан в §4 отчёта docs/team/14-s3-ci.md).

Почему отдельная БД: цикл удаляет все таблицы (``downgrade base``), поэтому
запускать его можно только на специально выделенной базе. Тест:
  * пропускается, если ``TEST_MIGRATION_DATABASE_URL`` не задан;
  * отказывается работать, если имя базы не похоже на выделенную под миграции
    (защита от случайного запуска на ``karier_db`` / ``karier_test_db``).

Полный цикл с созданием БД выполняет ``scripts/check_migrations.sh`` (его же
вызывает job ``migrations`` в .github/workflows/ci.yml).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_URL_ENV = "TEST_MIGRATION_DATABASE_URL"

# Базы, на которых прогонять цикл запрещено: это рабочий и общий тестовый стенд.
FORBIDDEN_DATABASES = {"karier_db", "karier_test_db", "postgres", "karier_demo_scratch"}

# --- Известный baseline-дрейф (S-10), не является регрессией ------------------
# Зафиксировано 2026-11-25 (проверка V1): docs/team/11-v1-acceptance.md §6,
# docs/team/13-r2-review.md (оговорка C1). Итого 29 операций.
# Как обновлять при легитимных изменениях схемы — docs/team/14-s3-ci.md §8.
BASELINE_DATE = "2026-11-25"
BASELINE_SOURCE = "docs/team/11-v1-acceptance.md §6; docs/team/13-r2-review.md (C1)"
BASELINE_OPS_COUNT = 29

KNOWN_REMOVED_INDEXES = {
    "gis.asset_types.ix_asset_types_parent",
    "gis.assets.ix_assets_schema_block",
    "ops.defects.ix_defects_active",
    "ops.maintenance_entries.ix_maintenance_at",
}
KNOWN_ADDED_FKS = {
    "gis.assets(schema_block_id)",
    "ops.defects(deleted_by)",
}
KNOWN_REMOVED_TABLE_COMMENTS = {
    "audit.audit_log",
    "auth.credentials",
    "auth.employees",
    "auth.mfa_factors",
    "auth.sessions",
    "gis.asset_moves",
    "gis.asset_ports",
    "gis.asset_types",
    "gis.assets",
    "gis.lines",
    "gis.links",
    "gis.map_layers",
    "gis.pits",
    "gis.schema_blocks",
    "gis.switching_ops",
    "ops.change_log",
    "ops.conflicts",
    "ops.defects",
    "ops.documents",
    "ops.inspection_items",
    "ops.inspections",
    "ops.media",
    "ops.sync_ops",
}

#: Схемы, которыми управляет проект (как в alembic/env.py): таблицы прототипа в
#: public не трогаем.
MANAGED_SCHEMAS = {"auth", "audit", "gis", "ops"}

pytestmark = pytest.mark.integration


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess[str]:
    """Запустить alembic в backend-v2 с подменённым DATABASE_URL."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        # alembic пишет сообщения миграций по-русски; на Windows локаль cp1251,
        # поэтому декодируем явно UTF-8, иначе поток падает с UnicodeDecodeError.
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> None:
    assert result.returncode == 0, (
        f"alembic {what} завершился с кодом {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )


@pytest.fixture(scope="module")
def migration_url() -> str:
    """DSN выделенной БД для цикла миграций (или skip с явной причиной)."""
    raw = (os.environ.get(MIGRATION_URL_ENV) or "").strip()
    if not raw:
        pytest.skip(
            f"{MIGRATION_URL_ENV} не задан: цикл upgrade/downgrade/upgrade удаляет все таблицы, "
            "поэтому выполняется только на отдельной БД. Запустите "
            "`bash backend-v2/scripts/check_migrations.sh` (он создаёт БД и выставляет "
            "переменную) или задайте TEST_MIGRATION_DATABASE_URL вручную."
        )

    url = make_url(raw)
    database = (url.database or "").strip()
    assert database, f"{MIGRATION_URL_ENV} не содержит имени базы: {raw}"
    assert database not in FORBIDDEN_DATABASES, (
        f"{MIGRATION_URL_ENV} указывает на запрещённую базу '{database}': цикл "
        "downgrade base уничтожит её данные. Нужна отдельная база, например "
        "karier_migrations_test."
    )
    assert "migrat" in database.lower(), (
        f"{MIGRATION_URL_ENV} = '{database}': имя базы должно содержать 'migration', "
        "чтобы нельзя было случайно перепутать её с рабочей или тестовой."
    )
    return raw


def _table_exists(url: str, schema: str, table: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            found = conn.execute(
                text(
                    "select 1 from information_schema.tables "
                    "where table_schema = :schema and table_name = :table"
                ),
                {"schema": schema, "table": table},
            ).scalar()
        return bool(found)
    finally:
        engine.dispose()


def _current_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("select version_num from public.alembic_version")).scalar()
        return row
    finally:
        engine.dispose()


def _normalize_ops(diff: list) -> set[str]:
    """Привести вывод compare_metadata к стабильным строковым подписям."""
    result: set[str] = set()

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            kind, obj = item[0], item[1]
            if kind in {"add_index", "remove_index"}:
                table = obj.table
                result.add(f"{kind}:{table.schema}.{table.name}.{obj.name}")
            elif kind in {"add_fk", "remove_fk"}:
                table = obj.table
                columns = ",".join(column.name for column in obj.columns)
                result.add(f"{kind}:{table.schema}.{table.name}({columns})")
            elif kind in {"add_table_comment", "remove_table_comment"}:
                result.add(f"{kind}:{obj.schema}.{obj.name}")
            else:
                schema = getattr(obj, "schema", None)
                name = getattr(obj, "name", None)
                result.add(f"{kind}:{schema}.{name}")

    walk(diff)
    return result


def _autogenerate_diff(url: str) -> set[str]:
    """Посчитать расхождения моделей и БД (как alembic check, но в памяти)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base  # noqa: PLC0415 - импорт после проверки окружения

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "compare_type": True,
                    "include_schemas": True,
                    "version_table_schema": "public",
                    "include_object": lambda obj, name, type_, reflected, compare_to: (
                        type_ != "table" or getattr(obj, "schema", None) in MANAGED_SCHEMAS
                    ),
                },
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    return _normalize_ops(diff)


def test_single_alembic_head(migration_url: str) -> None:
    """Голова ровно одна: две головы = сломанная линейка миграций."""
    result = _alembic("heads", database_url=migration_url)
    _require_ok(result, "heads")
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"ожидалась одна голова, получено {len(heads)}:\n" + "\n".join(heads)


def test_upgrade_downgrade_upgrade(migration_url: str) -> None:
    """upgrade head → downgrade base → upgrade head на отдельной БД."""
    started = time.monotonic()

    upgrade_one = _alembic("upgrade", "head", database_url=migration_url)
    _require_ok(upgrade_one, "upgrade head (1)")
    head_after_upgrade = _current_revision(migration_url)
    assert head_after_upgrade, "после upgrade head в public.alembic_version пусто"
    assert _table_exists(migration_url, "gis", "assets"), "после upgrade head нет gis.assets"

    downgrade = _alembic("downgrade", "base", database_url=migration_url)
    _require_ok(downgrade, "downgrade base")
    assert not _table_exists(migration_url, "gis", "assets"), (
        "после downgrade base таблица gis.assets осталась: downgrade неполный"
    )
    assert not _table_exists(migration_url, "auth", "employees"), (
        "после downgrade base таблица auth.employees осталась: downgrade неполный"
    )

    upgrade_two = _alembic("upgrade", "head", database_url=migration_url)
    _require_ok(upgrade_two, "upgrade head (2)")
    assert _current_revision(migration_url) == head_after_upgrade, (
        "после повторного upgrade head ревизия не совпала с первой"
    )
    assert _table_exists(migration_url, "gis", "assets"), "повторный upgrade head не создал gis.assets"

    elapsed = time.monotonic() - started
    assert elapsed < 300, f"цикл миграций занял слишком много времени: {elapsed:.1f} c"


def test_autogenerate_has_only_known_drift(migration_url: str) -> None:
    """После upgrade head autogenerate не должен показывать ничего нового."""
    result = _alembic("upgrade", "head", database_url=migration_url)
    _require_ok(result, "upgrade head")

    actual = _autogenerate_diff(migration_url)

    known = (
        {f"remove_index:{name}" for name in KNOWN_REMOVED_INDEXES}
        | {f"add_fk:{name}" for name in KNOWN_ADDED_FKS}
        | {f"remove_table_comment:{name}" for name in KNOWN_REMOVED_TABLE_COMMENTS}
    )
    assert len(known) == BASELINE_OPS_COUNT, (
        f"baseline от {BASELINE_DATE} должен содержать {BASELINE_OPS_COUNT} операций "
        f"({BASELINE_SOURCE}), а в KNOWN_* сейчас {len(known)}: "
        "правка списка без причины ломает смысл проверки"
    )
    unexpected = actual - known
    assert not unexpected, (
        "autogenerate показал расхождения вне известного baseline-дрейфа (S-10). "
        "Значит модель и миграции разошлись — нужна миграция или правка модели:\n  "
        + "\n  ".join(sorted(unexpected))
    )

    vanished = known - actual
    assert not vanished, (
        "часть известного дрейфа исчезла — обновите KNOWN_* в tests/test_migrations.py "
        "(это ожидаемо после задачи S-10, которая приводит модели и БД к согласию):\n  "
        + "\n  ".join(sorted(vanished))
    )
