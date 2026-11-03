# Karier GIS API — backend-v2 (Спринт 1)

Новый бэкенд: **FastAPI + SQLAlchemy 2 + PostgreSQL (psycopg 3) + Alembic**.
Старый `backend/` не тронут и остаётся для справки; новая система живёт в тех же
схемах БД (`auth`, `audit`), что и прототип в `public`, и с ним не пересекается.

## Что реализовано

| Блок | Детали |
|---|---|
| Закрытая регистрация | `POST /api/auth/register/start` → код на Telegram/вручную → `verify` → `complete` (пароль) |
| Вход | табельный + пароль, Argon2id (m=64 МБ, t=2), блокировка 5 → 1 мин, 10 → 15 мин, 15 → 60 мин |
| 2FA | TOTP (RFC 6238), окно ±30 c, защита от повторного использования кода, 10 резервных кодов |
| Сессии | access-JWT 15 мин в памяти клиента + refresh в `httpOnly` cookie (30 дней), ротация, детект повторного использования → отзыв семейства |
| Роли | `admin`, `operator`, `viewer`, `contractor`; 12 прав; проверка **на сервере** (`require_permission`) |
| Сотрудники | CRUD, блокировка, сброс пароля (временный), повторная отправка кода |
| Аудит | `audit.audit_log`, append-only (триггер в БД), `request_id`, IP, UA, before/after |

### Спринт 2: реестр и карта

| Блок | Детали |
|---|---|
| Схема `gis` | `pits`, `map_layers`, `asset_types`, `assets`, `asset_ports` (миграция `0002_sprint2_gis`) |
| Координаты | `assets.x/y` — **метры** местной СК карьера; подложка привязана масштабом (`meters_per_pixel`) |
| Справочник | 15 типов с иконками, шаблонами портов и JSON-схемами атрибутов; расширяется через API |
| API | `GET/POST /api/assets`, `GET/PATCH/DELETE /api/assets/{id}`, `GET /api/assets/{id}/power-path`, `GET /api/asset-types`, `GET /api/map/layers/active` |
| Права | чтение — любой вход; создание/правка — `asset.create`; удаление — `asset.delete` |
| Валидация | тип, обязательные атрибуты, границы карты, уникальность кода, `expected_version` → 409 |

## Структура

```
backend-v2/
├── app/
│   ├── api/            # роутеры и зависимости (deps, middleware)
│   ├── core/           # конфиг, безопасность, ошибки, лимиты, uuid7
│   ├── db/             # engine и сессии
│   ├── models/         # SQLAlchemy: auth.py, audit.py
│   ├── schemas/        # Pydantic v2
│   ├── services/       # бизнес-логика: auth, audit, notify
│   └── main.py
├── alembic/versions/0001_sprint1_auth.py
├── alembic/versions/0002_sprint2_gis.py
├── scripts/
│   ├── smoke.ps1       # сквозной тест через HTTP (26 проверок)
│   └── smoke-result.txt
├── tests/              # pytest: 20 тестов (9 auth + 11 ГИС)
├── seed.py
├── requirements.txt
└── .env / .env.example
```

## Запуск

```powershell
cd C:\karier\backend-v2

# 1. окружение (venv уже создан; если ставить с нуля — см. примечание ниже)
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. настройки
Copy-Item .env.example .env      # и проверьте DATABASE_URL / SECRET_KEY

# 3. схема БД
.\venv\Scripts\python.exe -m alembic upgrade head

# 4. роли, права, тестовые сотрудники
.\venv\Scripts\python.exe seed.py

# 4b. карьер, подложка, справочник типов и 16 объектов с координатами
.\venv\Scripts\python.exe seed_gis.py

# 5. сервер
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Документация API: http://127.0.0.1:8001/docs

## Тестовые учётные записи

| Табельный | Пароль | Роль | 2FA |
|---|---|---|---|
| 000001 | `admin` | администратор | выключена, пароль помечен временным |
| 000002 | `operator123` | оператор | **включена** (TOTP) |
| 000003 | — | оператор | регистрация по коду (демо закрытой регистрации) |

Секрет TOTP для 000002 печатается при `seed.py`. Текущий секрет стенда:
`VIKFSSCEEHU4M2CQCPAQYCZAMMUYCZIH` — добавьте его в Google Authenticator / Aegis
или сгенерируйте код командой:

```powershell
.\venv\Scripts\python.exe -c "import pyotp; print(pyotp.TOTP('VIKFSSCEEHU4M2CQCPAQYCZAMMUYCZIH').now())"
```

## Проверка

```powershell
# юнит/API-тесты
.\venv\Scripts\python.exe -m pytest -q

# сквозной сценарий по HTTP (сервер должен быть запущен)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1
```

`smoke.ps1` проверяет: вход, 2FA, закрытую регистрацию, запрет доступа оператору
(403), создание сотрудника и дубликат (409), сброс пароля, блокировку (423),
refresh/logout, записи в журнале и неизменяемость `audit_log`.

Если TOTP-код «не подходит» после нескольких прогонов подряд — это сработала
защита от replay (тот же 30-секундный интервал). `smoke.ps1` сам сбрасывает
счётчик; вручную: `update auth.mfa_factors set last_counter = null`.

## Решения, которые стоит знать

* **Пароли** — Argon2id через `argon2-cffi` (не `passlib`: библиотека не
  поддерживается с 2020 и конфликтует с новыми версиями Python).
* **Refresh-токен** — не JWT, а непрозрачная строка; в БД лежит только HMAC-хэш.
  Так его можно отозвать, и `prev_refresh_hash` позволяет заметить кражу.
* **Журнал аудита** пишется отдельной сессией после ответа, поэтому фиксируется
  даже при откате бизнес-транзакции. `UPDATE`/`DELETE` запрещены триггером.
* **Аудит-события** не содержат паролей, TOTP-секретов и кодов — только факты и
  идентификаторы.
* **Лимиты** — in-memory (один процесс). В prod заменяются на Redis, интерфейс
  `limiter.allow(key, limit, window)` сохранён.

## Ограничения стенда

* Отправка кода в Telegram — заглушка: код печатается в консоль и (при
  `EXPOSE_OTP_CODE=true`) возвращается в ответе. Реальная отправка — один метод
  в `app/services/notify.py`.
* `COOKIE_SECURE=false` для http://localhost. В prod — `true` и HTTPS.
* Миграция живёт в схемах `auth`/`audit` общей базы `karier_db`; таблицы
  прототипа в `public` не затрагиваются (`include_object` в `alembic/env.py`).

## Примечания по окружению (только для этого стенда)

Песочница блокирует `spawn` с pipe-каналами, поэтому:

* `venv` скопирован из `backend/venv` (создание с нуля падает на `ensurepip`);
* в `venv/Lib/site-packages/sitecustomize.py` лежит обход: `tempfile.mkdtemp`
  создаёт каталоги с наследуемыми правами, иначе pip не может писать во
  временные файлы.

На обычной машине ничего из этого не нужно: `python -m venv venv` работает штатно.
