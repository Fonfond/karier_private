#!/usr/bin/env bash
# Проверка миграций Alembic «Карьер» на ОТДЕЛЬНОЙ базе (S-3).
#
# Что делает:
#   1. создаёт (пересоздаёт) пустую базу MIGRATION_DB_NAME;
#   2. прогоняет цикл: alembic upgrade head → downgrade base → upgrade head;
#   3. запускает pytest tests/test_migrations.py — там проверяются голова,
#      полнота downgrade и отсутствие НОВОГО дрейфа моделей/БД (известный
#      baseline-дрейф S-10 перечислен в тесте);
#   4. печатает тайминги каждого шага.
#
# Рабочую (karier_db) и общую тестовую (karier_test_db) базы скрипт не трогает:
# имя базы для цикла обязано содержать "migration", иначе тест падает.
#
# Запуск (Windows, Git Bash):
#   PGUSER=postgres bash backend-v2/scripts/check_migrations.sh
# Запуск (CI, ubuntu):
#   bash backend-v2/scripts/check_migrations.sh   # с TEST_MIGRATION_DATABASE_URL
#
# Переменные:
#   TEST_MIGRATION_DATABASE_URL — готовый DSN отдельной БД (иначе собирается
#                                 из TEST_DATABASE_URL или tests/.env.test);
#   MIGRATION_DB_NAME           — имя базы для цикла (default karier_migrations_test);
#   PGUSER / PGPASSWORD         — админ для create/drop database (default: из DSN);
#   MIGRATION_ADMIN_DB          — служебная база для CREATE DATABASE (default postgres);
#   MIGRATION_KEEP_DB=1         — не удалять базу после проверки;
#   PYTHON_BIN                  — интерпретатор (default: venv проекта).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # backend-v2
DB_NAME="${MIGRATION_DB_NAME:-karier_migrations_test}"
ADMIN_DB="${MIGRATION_ADMIN_DB:-postgres}"

if [[ -z "${PYTHON_BIN:-}" ]]; then
    if [[ -x "$HERE/venv/Scripts/python.exe" ]]; then
        PYTHON_BIN="$HERE/venv/Scripts/python.exe"
    elif [[ -x "$HERE/venv/bin/python" ]]; then
        PYTHON_BIN="$HERE/venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi

step() { printf '  %-28s %5s c\n' "$1" "$((SECONDS - $2))"; }

# --- 1. DSN отдельной базы ---------------------------------------------------
DSN="${TEST_MIGRATION_DATABASE_URL:-}"
if [[ -z "$DSN" ]]; then
    if [[ -n "${TEST_DATABASE_URL:-}" ]]; then
        SRC="$TEST_DATABASE_URL"
    elif [[ -f "$HERE/tests/.env.test" ]]; then
        # тот же файл, что читает tests/conftest.py
        SRC="$(grep -m1 -E '^(TEST_)?DATABASE_URL=' "$HERE/tests/.env.test" \
               | cut -d= -f2- | tr -d '\r"' | tr -d "'" || true)"
    else
        echo "ОШИБКА: не задан TEST_MIGRATION_DATABASE_URL и не найден tests/.env.test" >&2
        exit 2
    fi
    DSN="${SRC%/*}/$DB_NAME"
fi

if [[ ! "$DSN" =~ ^postgresql(\+[a-z0-9]+)?://([^:/@]+):([^@]*)@([^:/]+):([0-9]+)/(.+)$ ]]; then
    echo "ОШИБКА: не разобрать DSN отдельной БД: ${DSN%%:*}://..." >&2
    exit 2
fi
DB_USER="${BASH_REMATCH[2]}"
DB_PASS="${BASH_REMATCH[3]}"
DB_HOST="${BASH_REMATCH[4]}"
DB_PORT="${BASH_REMATCH[5]}"
DB_OLD="${BASH_REMATCH[6]}"
MIG_DSN="${DSN%/*}/$DB_NAME"

case "$DB_NAME" in
    *karier_db|*karier_test_db|postgres)
        echo "ОШИБКА: '$DB_NAME' — рабочая/общая база, цикл downgrade её уничтожит" >&2
        exit 2
        ;;
esac
if [[ "$DB_NAME" != *migration* ]]; then
    echo "ОШИБКА: имя базы '$DB_NAME' должно содержать 'migration' (защита от опечатки)" >&2
    exit 2
fi

echo "Проверка миграций:"
echo "  база:   $DB_NAME (было в DSN: $DB_OLD)"
echo "  сервер: $DB_HOST:$DB_PORT, владелец: $DB_USER"
echo "  python: $PYTHON_BIN"
echo

export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

# --- 2. Пересоздаём пустую базу ---------------------------------------------
ADMIN_USER="${PGUSER:-$DB_USER}"
ADMIN_PASS="${PGPASSWORD-$DB_PASS}"

psql_admin() {
    PGPASSWORD="$ADMIN_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" \
        -d "$ADMIN_DB" -v ON_ERROR_STOP=1 "$@"
}

START_ALL=$SECONDS
echo "1) Пересоздаём пустую базу $DB_NAME"
psql_admin -q -c "select pg_terminate_backend(pid) from pg_stat_activity where datname = '$DB_NAME';" >/dev/null
psql_admin -q -c "drop database if exists \"$DB_NAME\";" >/dev/null
psql_admin -q -c "create database \"$DB_NAME\" owner \"$DB_USER\" encoding 'UTF8' template template0;" >/dev/null
echo "   ok"

# --- 3. Цикл миграций -------------------------------------------------------
echo "2) upgrade head → downgrade base → upgrade head"
T=$SECONDS
(cd "$HERE" && DATABASE_URL="$MIG_DSN" "$PYTHON_BIN" -m alembic upgrade head >/dev/null)
step "upgrade head" "$T"
T=$SECONDS
(cd "$HERE" && DATABASE_URL="$MIG_DSN" "$PYTHON_BIN" -m alembic downgrade base >/dev/null)
step "downgrade base" "$T"
T=$SECONDS
(cd "$HERE" && DATABASE_URL="$MIG_DSN" "$PYTHON_BIN" -m alembic upgrade head >/dev/null)
step "upgrade head (повтор)" "$T"

# --- 4. Проверки pytest -----------------------------------------------------
echo "3) pytest tests/test_migrations.py (голова, downgrade, autogenerate)"
T=$SECONDS
(
    cd "$HERE"
    TEST_MIGRATION_DATABASE_URL="$MIG_DSN" \
    TEST_DATABASE_URL="${TEST_DATABASE_URL:-}" \
    "$PYTHON_BIN" -m pytest -q tests/test_migrations.py
)
step "pytest" "$T"

echo
step "всего" "$START_ALL"

# --- 5. Уборка --------------------------------------------------------------
if [[ "${MIGRATION_KEEP_DB:-0}" != "1" ]]; then
    psql_admin -q -c "select pg_terminate_backend(pid) from pg_stat_activity where datname = '$DB_NAME';" >/dev/null
    psql_admin -q -c "drop database if exists \"$DB_NAME\";" >/dev/null
    echo "База $DB_NAME удалена (MIGRATION_KEEP_DB=1 — оставить)."
else
    echo "База $DB_NAME оставлена (MIGRATION_KEEP_DB=1)."
fi

echo "OK: миграции накатываются, откатываются и не дают нового дрейфа."
