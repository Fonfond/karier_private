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

### Спринт 3: топология, схема, документы

| Блок | Детали |
|---|---|
| Схема `gis` | `lines`, `links`, `switching_ops` (миграция `0003_sprint3_topology`) |
| Схема `ops` | `documents` — файлы объекта: `schematic`, `settings`, `manual`, `other` |
| Расчёт питания | Обход графа портов: источники → включённые связи → внутренние порты включённых объектов |
| Валидация | OUT→IN, совпадение напряжения, дубликат пары, цикл в основной схеме |
| Проверки схемы | `GET /api/topology/issues` — объекты без ввода, кольца, несовпадение напряжения |
| Переключения | `POST /api/assets/{id}/state` (статус, заземление + причина), журнал `switching_ops` |
| Иерархия | `GET /api/assets/{id}/children` — секции и ячейки внутри ПС/БКРУ |
| Документы | загрузка 25 МБ, выдача по короткоживущей ссылке (`token`, 30 мин), локальное хранилище `var/documents` |

### Спринт 4: фото, обходы, дефекты

| Блок | Детали |
|---|---|
| Схема `ops` | `inspections`, `inspection_items`, `defects`, `media` (миграция `0004_sprint4_ops`) |
| Фото | `POST /api/assets/{id}/media` (multipart), `GET /api/media/{id}/file?token=`, удаление автором или админом |
| Метаданные | `captured_at`, `lat/lon`, `geo_source`, автор снимком, `sha256`, `watermark_applied`, `exif` |
| Хранилище | `app/services/storage.py`: локальный диск; при `BLOB_READ_WRITE_TOKEN` — Vercel Blob, код тот же |
| Обходы | `POST /api/inspections`, отметки по объектам, `POST /{id}/submit`, «мой обход» |
| Дефекты | создание, список с фильтрами, закрытие только с `photo_after_id` (иначе 422) |
| История | `GET /api/assets/{id}/history` — обходы, дефекты, фото, переключения |

### Спринт 5: синхронизация и перемещения

| Блок | Детали |
|---|---|
| Журнал | `ops.change_log` + триггеры на `gis.assets`, `gis.links`, `ops.defects` (автор из `karier.actor_id`) |
| Идемпотентность | `ops.sync_ops` по `op_id`; повторный push возвращает `duplicate` |
| Push | `POST /api/sync/push` — до 200 операций, результат и `server_seq` |
| Pull | `GET /api/sync/pull?since=&limit=` — дельта с курсором |
| Конфликты | `ops.conflicts`; LWW по `client_ts` против `updated_at`, оба исхода фиксируются |
| Перемещения | `gis.asset_moves`, `POST /api/assets/{id}/move`, `GET /api/assets/{id}/moves` |
| Проверка | `pytest` — 44 теста, включая идемпотентность, LWW и сохранение графа после перемещения |

### Спринт 8: CRUD справочника и ручная схема

| Блок | Детали |
|---|---|
| Иерархия | `gis.asset_types.parent_id` — категория → тип → подтип, запрет циклов |
| Типы | `GET /asset-types?include_inactive=`, `POST`, `PATCH`, `DELETE` (мягко, с проверкой использования) |
| Раскладка | `gis.assets.schema_x/schema_y`, `PUT /topology/layout` (только роль admin) |
| Граф | `GET /topology/graph` отдаёт `schema_x/y` и порты — по ним схема соединяет узлы |
| Сотрудники | `DELETE /employees/{id}` — увольнение с отзывом сессий, защита последнего админа |
| Права | новый `require_admin`; типы — `settings.edit`, объекты — `asset.create` |

### Спринт 9: UX-полировка

| Блок | Детали |
|---|---|
| Позиции портов | `gis.asset_ports.schema_x/schema_y` (доли 0…1), отдаются в графе и связях |
| Раскладка | `PUT /topology/layout` принимает `items` и `ports` |
| Удаление людей | `DELETE /employees/{id}/permanent` с защитой истории (`employee.has_history`) |
| Тесты | 68 pytest |

### Спринт 12: подложки и связи

| Блок | Детали |
|---|---|
| Карты | POST /api/map/layers (multipart, admin), GET /api/map/layers, GET /api/map/layers/{id}/image |
| Связи | граф отдаёт марку, длину, сечение и версию связи для редактора |
| Тесты | 84 pytest |

### Спринты 6–7: дашборд, отчёты, деплой

| Блок | Детали |
|---|---|
| Дашборд | `GET /api/dashboard/summary` — статусы, дефекты по критичности, обходы за неделю, «кукушки» |
| Excel | `POST /api/reports/token` + `GET /api/reports/export?token=`; реестр, дефекты, переключения, обходы |
| PDF | паспорт объекта: карточка, путь питания, QR, до трёх фото (reportlab) |
| Токены | короткоживущие (30 мин), привязаны к сотруднику, проверяют право `report.export` |
| Безопасность | security-заголовки, HSTS вне dev, предупреждения о `COOKIE_SECURE`/дев-секрете |
| Демо | `python seed_demo.py` — фото, дефекты, обход, перемещения |

### Панель базы данных (локально, в браузере)

```powershell
.\venv\Scripts\python -u tools\db_admin.py
# http://127.0.0.1:8010/?token=... — ссылка печатается при старте
```

Просмотр таблиц `gis`/`ops`/`auth`/`audit`/`public`, поиск, выгрузка CSV и SQL-консоль.
Изменения — в два шага: «Проверить» выполняет запрос и откатывает (`ROLLBACK`), «Применить» фиксирует.
`DROP`/`ALTER`/`TRUNCATE` запрещены. Токен хранится в `var/db_admin_token.txt`.

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
├── alembic/versions/0003_sprint3_topology.py
├── alembic/versions/0004_sprint4_ops.py
├── alembic/versions/0005_sprint5_sync.py
├── scripts/
│   ├── smoke.ps1       # сквозной тест через HTTP (26 проверок)
│   └── smoke-result.txt
├── tests/              # pytest: 61 тест (auth, реестр, топология, обходы, синхронизация, отчёты, админка)
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

# 4c. секции шин, ячейки, опоры, линии и связи (топология Спринта 3)
.\venv\Scripts\python.exe seed_topology.py

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
