"""Pytest-фикстуры: клиент API поверх изолированной тестовой БД.

Тесты создают, меняют и удаляют данные, поэтому работают ТОЛЬКО на `karier_test_db`.
Рабочая база `karier_db` не должна открываться даже случайно: адрес БД подменяется
до импорта приложения, а затем проверяется, что приложение действительно видит
тестовую базу — иначе падение до первого теста (fail fast).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- Изоляция тестовой БД (обязательно до импорта app) ---------------------
TEST_DB_NAME = "karier_test_db"
# DSN тестовой БД берётся из окружения (TEST_DATABASE_URL) или из локального
# файла backend-v2/tests/.env.test. Оба варианта не коммитятся, пароля в коде нет:
# см. backend-v2/.env и docs/team/08-s1-repo-hygiene.md.
ENV_TEST_FILE = Path(__file__).resolve().with_name(".env.test")


def _read_env_test(path: Path) -> str | None:
    """Взять TEST_DATABASE_URL из tests/.env.test (файл в .gitignore)."""
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in ("TEST_DATABASE_URL", "DATABASE_URL"):
            return value.strip().strip('"').strip("'")
    return None


def _database_name(url: str) -> str:
    """Имя базы из URL или пустая строка, если URL не разбирается."""
    try:
        return make_url(url).database or ""
    except Exception:  # noqa: BLE001 - нужен понятный отказ, а не трейс
        return ""


test_database_url = os.environ.get("TEST_DATABASE_URL") or _read_env_test(ENV_TEST_FILE)

if not test_database_url:
    raise RuntimeError(
        "Не задан DSN тестовой БД. Укажите один из вариантов:\n"
        "  1) переменную окружения "
        "TEST_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/karier_test_db\n"
        "  2) файл backend-v2/tests/.env.test со строкой\n"
        "     TEST_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/karier_test_db\n"
        "Пароль роли karier_user лежит в backend-v2/.env (переменная DATABASE_URL); "
        "в коде и в репозитории его нет, .env.test добавлен в .gitignore."
    )


# Явно заданный DATABASE_URL — это осознанное намерение запустить на конкретной
# базе: если это не тестовая база, отказываем до первого теста, а не подменяем молча.
explicit_url = os.environ.get("DATABASE_URL")
if explicit_url and _database_name(explicit_url) != TEST_DB_NAME:
    raise RuntimeError(
        "Тесты нельзя запускать на базе '"
        f"{_database_name(explicit_url) or explicit_url}': разрешена только '{TEST_DB_NAME}'. "
        "Уберите DATABASE_URL или задайте TEST_DATABASE_URL."
    )

os.environ["DATABASE_URL"] = test_database_url

if _database_name(test_database_url) != TEST_DB_NAME:
    raise RuntimeError(
        "Тесты разрешены только на базе '"
        f"{TEST_DB_NAME}', а указана '{_database_name(test_database_url) or test_database_url}'. "
        "Проверьте TEST_DATABASE_URL."
    )

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from sqlalchemy import text  # noqa: E402

if _database_name(settings.DATABASE_URL) != TEST_DB_NAME:
    raise RuntimeError(
        "Приложение подключилось не к тестовой БД: "
        f"'{_database_name(settings.DATABASE_URL) or settings.DATABASE_URL}'. "
        "Запуск тестов на рабочей базе запрещён."
    )


@pytest.fixture(autouse=True)
def heal_topology():
    """Перед каждым тестом возвращаем схему в эталонное состояние.

    Тесты переключают ячейки и связи, поэтому без этого они влияли бы друг на друга.
    """
    db = SessionLocal()
    try:
        db.execute(
            text(
                "update gis.assets set status='on', grounded=false "
                "where code in ('BKRU1-IN1','BKRU1-OUT1','BKRU1-OUT2','BKRU1-OUT3')"
            )
        )
        db.execute(
            text("update gis.assets set status='off', grounded=false where code in ('BKRU1-IN2','BKRU1-SEC')")
        )
        db.execute(
            text("update gis.assets set status='on', grounded=false where code='KTP-14'")
        )
        db.execute(text("update gis.links set state='connected' where deleted_at is null"))
        db.execute(
            text(
                "update gis.links set state='open' "
                "where deleted_at is null and (link_type='jumper' or feed_role='backup')"
            )
        )
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_tokens(client: TestClient) -> dict:
    response = client.post("/api/auth/login", json={"tab_no": "000001", "password": "admin"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="session")
def admin_headers(admin_tokens: dict) -> dict:
    return {"Authorization": f"Bearer {admin_tokens['access_token']}"}


@pytest.fixture(scope="session")
def operator_secret() -> str:
    """TOTP-секрет оператора `000002`.

    `seed.py` генерирует секрет случайно, поэтому по умолчанию он читается из
    тестовой БД; переменная `TEST_TOTP_SECRET` переопределяет значение.
    """
    override = os.environ.get("TEST_TOTP_SECRET")
    if override:
        return override

    from app.core.security import decrypt_secret  # noqa: PLC0415 - нужен после изоляции БД

    db = SessionLocal()
    try:
        secret_enc = db.execute(
            text(
                "select f.secret_enc from auth.mfa_factors f "
                "join auth.employees e on e.id = f.employee_id "
                "where e.tab_no = '000002' and f.kind = 'totp' and f.confirmed_at is not null"
            )
        ).scalar_one_or_none()
    finally:
        db.close()

    if not secret_enc:
        raise RuntimeError(
            "У оператора 000002 нет подключённой 2FA в тестовой БД — выполните seed.py."
        )
    return decrypt_secret(secret_enc).strip()
