#!/bin/sh
# Entrypoint API «Карьер» (backend-v2) для Docker/Compose.
#   1) ждёт PostgreSQL (по DATABASE_URL);
#   2) применяет миграции (alembic upgrade head);
#   3) готовит каталоги документов/медиа (обычно поверх томов);
#   4) запускает uvicorn — ровно один воркер по умолчанию.
# Секреты в образ не попадают: конфигурация приходит из окружения (compose/.env).
set -eu

: "${DATABASE_URL:?DATABASE_URL не задан — передайте его через .env или окружение compose}"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
API_WORKERS="${API_WORKERS:-1}"
DB_WAIT_TIMEOUT="${DB_WAIT_TIMEOUT:-90}"

echo "[entrypoint] ждём PostgreSQL (таймаут ${DB_WAIT_TIMEOUT}s)…"
python - "$DATABASE_URL" "$DB_WAIT_TIMEOUT" <<'PY'
import sys
import time

from sqlalchemy import create_engine, text

url, timeout = sys.argv[1], int(sys.argv[2])
deadline = time.monotonic() + timeout
last_error: Exception | None = None
while time.monotonic() < deadline:
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        print("[entrypoint] PostgreSQL доступен")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 — ждём любую ошибку подключения
        last_error = exc
        time.sleep(2)
print(f"[entrypoint] PostgreSQL недоступен за {timeout}s: {last_error}", file=sys.stderr)
sys.exit(1)
PY

mkdir -p "${DOCUMENTS_DIR:-var/documents}" "${MEDIA_DIR:-var/media}"

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] uvicorn ${API_HOST}:${API_PORT} (workers=${API_WORKERS})"
exec uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" --workers "$API_WORKERS"
