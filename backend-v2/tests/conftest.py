"""Pytest-фикстуры: клиент API поверх изолированной тестовой БД.

Тесты создают, меняют и удаляют данные, поэтому работают ТОЛЬКО на `karier_test_db`.
Рабочая база `karier_db` не должна открываться даже случайно: адрес БД подменяется
до импорта приложения, а затем проверяется, что приложение действительно видит
тестовую базу — иначе падение до первого теста (fail fast).
"""

from __future__ import annotations

import faulthandler
import os
import sys
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

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

# --- V1b-1: длинный TTL access-токена на время тестов ------------------------
# В проде токен живёт 15 минут. Полный прогон на медленной машине идёт дольше, и
# сессионный `admin_headers` начинал отдавать 401: один зависший тест превращался
# в каскад из 30 «ложных» падений (наблюдение V1b). В тестовом процессе живём с
# длинным TTL; переменная действует только внутри pytest и приоритетнее .env.
os.environ.setdefault("ACCESS_TOKEN_TTL_MIN", "720")

if _database_name(test_database_url) != TEST_DB_NAME:
    raise RuntimeError(
        "Тесты разрешены только на базе '"
        f"{TEST_DB_NAME}', а указана '{_database_name(test_database_url) or test_database_url}'. "
        "Проверьте TEST_DATABASE_URL."
    )

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

if _database_name(settings.DATABASE_URL) != TEST_DB_NAME:
    raise RuntimeError(
        "Приложение подключилось не к тестовой БД: "
        f"'{_database_name(settings.DATABASE_URL) or settings.DATABASE_URL}'. "
        "Запуск тестов на рабочей базе запрещён."
    )

# Токен должен переживать самый долгий прогон: иначе сессионный admin_headers
# начнёт отдавать 401 и утянет за собой десятки тестов (V1b-1).
if settings.ACCESS_TOKEN_TTL_MIN < 60:
    raise RuntimeError(
        "Для тестов нужен ACCESS_TOKEN_TTL_MIN >= 60 (сейчас "
        f"{settings.ACCESS_TOKEN_TTL_MIN}): иначе сессионный токен истекает посреди "
        "прогона и даёт каскад ложных 401. Уберите ACCESS_TOKEN_TTL_MIN из окружения."
    )

# V1b-2: сторож на тест. pytest-timeout в окружении нет, поэтому используем
# faulthandler: по истечении лимита печатается стек всех потоков и процесс
# завершается — прогон «падает» с понятным стеком, а не висит десятки минут.
TEST_TIMEOUT_SECONDS = float(os.environ.get("TEST_TIMEOUT_SECONDS", "180"))

# Таблицы, в которых тесты оставляют мусор. Порядок удаления важен:
# сначала связи, потом объекты (каскад уносит порты и блоки), затем линии,
# снимки, типы (на них RESTRICT) и сотрудники (каскад уносит credentials/mfa/sessions).
CLEANUP_TABLES = (
    "gis.links",
    "gis.assets",
    "gis.lines",
    "gis.schema_snapshots",
    "gis.asset_types",
    "auth.employees",
)


def _snapshot_ids() -> dict[str, set]:
    """Снимок PK до теста: всё, что было в БД раньше, уборка не затрагивает."""
    db = SessionLocal()
    try:
        return {table: set(db.scalars(text(f"select id from {table}")).all()) for table in CLEANUP_TABLES}
    finally:
        db.close()


def _delete_new_rows(keep: dict[str, set]) -> None:
    """Удалить строки, появившиеся во время теста (идемпотентно, с пропуском RESTRICT)."""
    db = SessionLocal()
    try:
        for table in CLEANUP_TABLES:
            new_ids = list(set(db.scalars(text(f"select id from {table}")).all()) - keep[table])
            for start in range(0, len(new_ids), 500):
                chunk = new_ids[start:start + 500]
                try:
                    db.execute(
                        text(f"delete from {table} where id in :ids").bindparams(
                            bindparam("ids", expanding=True)
                        ),
                        {"ids": chunk},
                    )
                    db.commit()
                except SQLAlchemyError as exc:
                    # Например, новый тип объекта, на который успел сослаться seeded-объект
                    # (gis.asset_types под RESTRICT). Не валим прогон из-за уборки, но
                    # оставляем след: пропущенные строки видны в warning'ах pytest.
                    db.rollback()
                    warnings.warn(
                        f"isolate_created_rows: не удалось убрать {table} "
                        f"({len(chunk)} строк): {exc.__class__.__name__}",
                        stacklevel=1,
                    )
    finally:
        db.close()


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


@pytest.fixture(autouse=True)
def isolate_created_rows(heal_topology):
    """Убрать за тестом: удаляем только строки, созданные внутри самого теста.

    Снимок PK берётся в setup (после `heal_topology`, то есть после всех
    session/seed-фикстур), поэтому seeded-данные и данные фикстур не трогаются:
    удаляется ровно разница «после минус до». Так база не растёт от прогона к
    прогону, и повторный запуск не упирается в уник-констрейнты (V1/S-9).
    """
    keep = _snapshot_ids()
    yield
    _delete_new_rows(keep)


@pytest.fixture(autouse=True)
def guard_test_timeout():
    """V1b-2: зависший тест не должен блокировать прогон (лимит TEST_TIMEOUT_SECONDS)."""
    faulthandler.dump_traceback_later(TEST_TIMEOUT_SECONDS, repeat=False, exit=True)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


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
