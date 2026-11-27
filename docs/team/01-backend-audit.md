# Аудит бэкенда «Карьер» (backend-v2): качество, безопасность, тестовые пробелы

**Дата:** 2026-11-24
**Автор:** backend-auditor (команда karier-improvements)
**Метод:** только чтение исходников (`backend-v2/app/**`, `alembic/versions/**`, `tests/**`, `seed*.py`, `mcp_server.py`, `requirements.txt`, `.env` — только имена переменных и несекретные флаги).
**Ограничения соблюдены:** pytest не запускался, код не менялся, к БД `karier_db` подключений не было, коммитов нет. Единственный записанный файл — этот отчёт.
**Вне охвата:** фронтенд (`src-v2`), инфраструктура деплоя, содержимое рабочей БД.

---

## 0. Паспорт кодовой базы и уточнение вводных

| Метрика | Факт | Комментарий |
|---|---|---|
| Стек | FastAPI 0.115.0, SQLAlchemy 2.0.36, psycopg 3, Alembic 1.14, Pydantic 2.x | `backend-v2/requirements.txt:5-13` |
| Объём `app/` | 11 363 строки, 61 файл | `services/` — 6 160, `api/routers/` — 2 488, `models/` — 970, `schemas/` — 1 020, `core/` — 400 |
| Роутеры | **15**, а не 18 | `backend-v2/app/main.py:183-197` — расхождение с вводными стоит зафиксировать в документации |
| Операции API | **117** — совпадает | 45 из них в одном файле `app/api/routers/gis.py` (38 %) |
| Миграции | 14, линейная цепочка `0001…0014`, один head | `alembic/versions/0014_schema_snapshots.py` |
| Тесты | 26 файлов, **162** тестовые функции — совпадает | `tests/test_*.py` |
| Схемы PostgreSQL | `auth`, `gis`, `ops`, `audit` | `app/models/*.py` |
| Модели | 24 таблицы | `app/models/__init__.py:22-54` |

Распределение операций по роутерам: `gis` 45, `schema_blocks` 13, `employees` 10, `auth` 7, `me` 7, `defects` 6, `documents` 5, `inspections` 5, `media` 4, `sync` 4, `map_layers` 3, `reports` 3, `moves` 2, `health` 2, `audit` 1.

**Общая оценка.** Каркас зрелый для внутреннего проекта: единый формат ошибок (RFC 7807), Argon2id с политикой паролей, шифрование TOTP-секретов AES-256-GCM, ротация refresh-токенов с детектом повторного использования, append-only журнал аудита на уровне БД (триггер), оптимистическая блокировка версиями, soft-delete в домене ГИС, разделение по схемам PostgreSQL. Проблемы концентрируются в трёх зонах:

1. **авторизация на офлайн-ветке `/sync/push`** обходит RBAC и позволяет менять электрическое состояние объекта без соответствующих прав;
2. **утечки секретов и отладочных возможностей** (OTP-код в ответе API и в логах, пароль БД в дефолте конфига, доверие `X-Forwarded-For`);
3. **стоимость запросов** — полный граф карьера пересчитывается на каждый запрос, плюс N+1 в списках и отсутствующие индексы.

---

## 1. Архитектура: связность `routers → services → models`

### 1.1. Что сделано хорошо

- Слои в целом соблюдаются: роутер разбирает HTTP, сервис работает с ORM, модель описывает таблицу; валидация — Pydantic-схемы (`app/schemas/*`), доменные ошибки — `ApiError`/`problem_response` (`app/core/errors.py:11-67`).
- Сборка графа схемы вынесена в сервис именно для переиспользования API и снимками — мотив зафиксирован в docstring (`app/services/schema_graph.py:1-6`), и это правильное решение: живая схема и снимок строятся одной функцией (`:26`, `:171`).
- Расчёт питания инкапсулирован (`app/services/topology.py`), роутер только сериализует результат (`app/api/routers/gis.py:363-408`).
- Часть роутеров тонкая и читаемая: `defects.py` (100 строк), `inspections.py` (90), `sync.py` (64), `health.py` (23).

### 1.2. «Толстые» роутеры и протёкшая бизнес-логика

| Место | Проблема |
|---|---|
| `backend-v2/app/api/routers/gis.py:1-881` (881 строка, 45 операций) | В одном файле 6-7 доменов: типы объектов, объекты, порты, связи, линии, граф, снимки, рамка/штамп, PDF, проверки, документы объекта, подложки, группы, журнал ТО, опоры ВЛ, комплектные блоки. |
| `backend-v2/app/api/routers/gis.py:772-795` | `ensure_ports` — роутер сам создаёт `AssetPort` и делает `db.commit()`, минуя сервис. |
| `backend-v2/app/api/routers/employees.py:1-390` | Почти вся логика администрирования сотрудников в роутере: `_serialize`, проверка «последний админ», защита break-glass, отзыв сессий. Сервиса `services/employees.py` нет вовсе. |
| `backend-v2/app/api/routers/employees.py:223`, `:264`, `:278` | Inline-импорты (`revoke_all_sessions`, `AuditLog`) внутри функций — признак циклических зависимостей и размытых границ. |
| `backend-v2/app/api/routers/documents.py:90-110` | `patch_document` правит поля модели и коммитит прямо в роутере, без сервисного слоя. |
| `backend-v2/app/api/routers/media.py:99-107` | Фильтр `purpose` применяется в Python уже после `limit` из БД — пагинация и фильтр работают «мимо друг друга». |
| `backend-v2/app/api/routers/schema_blocks.py:1-318` (13 операций) | Однотипные `gis.get_asset(...)` + вызов сервиса в каждом обработчике — просится свернуть в 3-4 доменных операции. |

### 1.3. Дублирование и мёртвый код

1. **Два разных `power_path`:** рабочий `app/services/topology.py:204-227` и устаревший `app/services/gis.py:569-630` (внутри даже текст «Полный расчёт по графу связей — Спринт 3»). Старый не вызывается ниоткуда — мёртвый код с вводящим в заблуждение docstring.
2. **Дублирующийся маршрут `GET /assets/{asset_id}/documents`:** объявлен дважды — `app/api/routers/gis.py:688-701` и `app/api/routers/documents.py:48-64`. `gis` подключается раньше (`app/main.py:188-189`), поэтому обработчик из `documents.py` недостижим: правки в нём не дают эффекта.
3. **Дубли полей в Pydantic-схемах:** `parent_id` дважды в `AssetBriefOut` (`app/schemas/gis.py:64` и `:72`), `has_maintenance` дважды в `AssetTypeOut` (`app/schemas/gis.py:132` и `:134`).
4. **Мёртвые функции/хелперы:** `app/services/gis.py:857-858` (`request_meta`), `app/services/media.py:177-179` (`file_response_payload` — «роутер решает», но роутер не вызывает), 5 неиспользуемых схемных импортов в шапке `app/api/routers/gis.py:37-41` (`GraphNodeOut`, `GraphEdgeOut`, `GraphBlockOut`, `GraphBlockChildOut`, `GraphJumperOut`).
5. **`__import__("app.models", fromlist=[...])` вместо импорта:** `app/services/groups.py:26-28`, `app/services/schema_blocks.py:146-150`, `:178-182`, `:506-512` — скрывает зависимости от линтеров и читателя.
6. **Двойная сериализация:** часть сервисов возвращает `dict`, часть — Pydantic-модели (`links_service.link_out` vs `media_service.media_out` vs `defects_service.defect_out`), из-за чего в роутерах 30+ конструкций `ModelOut(**service.func(...))`.
7. **Скрипты вне пакета:** `seed.py`, `seed_gis.py`, `seed_topology.py`, `seed_schema_blocks.py`, `seed_demo*.py`, `import_sketch_json.py`, `gen_sketch_json.py`, `clean_demo.py`, `reset_break_glass.py`, `mcp_server.py` — 10+ исполняемых файлов в корне `backend-v2/`, часть дублирует логику сервисов. Просится `app/cli/` или `scripts/`.

### 1.4. Транзакции: коммиты размазаны по слою сервисов

Единого unit-of-work нет — `db.commit()` встречается **в 30+ местах**; показательно:

- `app/services/gis.py:436` (`create_asset`), `:491` (`update_asset`), `:517` (`soft_delete`);
- `app/services/auth.py:196`, `:212`, `:252`, `:320`, `:336`, `:352`, `:432`, `:474`, `:500`, `:567`, `:614`, `:627`, `:665`, `:692`, `:716` — коммит в каждой ветке бизнес-операции;
- `app/services/schema_blocks.py:85` — `_create_child` коммитит **на каждого ребёнка**;
- `app/services/poles.py:124-134` — каждая опора создаётся отдельным `create_asset` со своим коммитом; `:136-187` — каждая связь отдельным `create_link` со своим коммитом.

Практическое следствие: генерация 200 опор — это ~400 независимых транзакций; падение на 150-й оставляет в БД «полулинию» без отката. То же в `app/services/composite.py:95-111` (комплект из 64 ячеек — 65 транзакций).

---

## 2. SQLAlchemy: запросы, индексы, транзакции, soft-delete, пагинация

### 2.1. Полный граф карьера на каждый запрос (главная проблема производительности)

`topology.load_graph()` (`app/services/topology.py:38-67`) поднимает **все** объекты карьера с портами (`selectinload`) и **все** связи, затем `energize()` (`:139-201`) обходит граф в Python. Кэша нет. Точки вызова:

| Ситуация | Сколько раз считается граф |
|---|---|
| `POST /assets/{id}/state` | **3 раза**: `before` (`app/services/state.py:46`), `_count_affected` (`:91`), `is_energized` (`:92`) |
| `GET /topology/issues` | **2 раза**: явно (`app/services/topology.py:361`) и внутри `energize` (`:362`) |
| `GET /topology/graph` | 1 раз на каждый рендер схемы (`app/services/schema_graph.py:28`) |
| `GET /assets/{id}/children` | 1 раз только чтобы узнать `energized` (`app/api/routers/gis.py:221`) |
| `GET /assets/{id}/power-path` | 1 раз (`app/services/topology.py:206`) |
| `GET /dashboard/summary` | 1 раз + отдельный запрос истории **на каждый** мобильный объект (`app/services/analytics.py:25`, `:74-79`) |
| `GET /topology/schema.pdf` | 1 раз (PDF собирается целиком в память) |

При 1 000 объектов и 1 500 связей это десятки тысяч ORM-объектов и три полных чтения таблиц на одно переключение. Нужен либо кэш по `pit_id` с инвалидацией при записи в `gis.assets`/`gis.links`, либо инкрементальный пересчёт, либо перенос обхода в SQL (рекурсивный CTE).

### 2.2. N+1 в списках

| Место | Что происходит | Оценка запросов |
|---|---|---|
| `app/api/routers/gis.py:222-250` (`asset_children`) | `child.ports` подгружается лениво на каждого ребёнка; `selectinload` не указан | 1 + N |
| `app/services/defects.py:205-226` (`defect_out`) | на каждый дефект: `count(Media)`, 2 × `db.get(Employee)`, 2 × `db.get(Media)` через `_photo` | 1 + 5N (100 дефектов → ~500 запросов) |
| `app/services/inspections.py:175-202` | на каждый обход: 2 агрегата + `db.get(Employee)` + `item.asset` | 1 + 3N |
| `app/services/analytics.py:70-97` | последнее перемещение — отдельный запрос на каждый мобильный объект | 1 + M |
| `app/services/reports.py:161-181` (`defects_xlsx`) | `db.get(Employee, ...)` в строках 175 и 177 на каждый дефект | 1 + 2N |
| `app/services/reports.py:237-274` (`inspections_xlsx`) | один и тот же `select(InspectionItem)` выполняется дважды в двух циклах | 2 × N |
| `app/services/gis.py:288-292` (`type_out`) | `count(Asset)` на каждый тип справочника | 1 + T |
| `app/services/schema_snapshots.py:42`, `:45` | `db.get(Employee)` на автора и публикующего для каждого снимка | 1 + 2N |
| `app/services/moves.py:92` | `db.get(Employee)` на каждое перемещение | 1 + N |

### 2.3. Индексы

Что есть (`alembic/versions/0001…0014`): `ix_assets_pit_type`, `ix_assets_parent`, `ix_assets_mobile`, `ix_asset_ports_asset`, `ix_links_from/to/line` + частичный уникальный `uq_links_pair_active`, `ix_defects_asset`, `ix_defects_status`, `ix_media_asset/defect/inspection`, `ix_inspection_items_*`, `ix_documents_asset`, `ix_audit_at/actor/entity`, `ix_sessions_*`, `ix_change_log_*`, `ix_schema_snapshots_pit_status`.

Чего **нет**, но запросы этого требуют:

| Таблица | Нужный индекс | Почему |
|---|---|---|
| `gis.links` | `(pit_id) WHERE deleted_at IS NULL` | `app/services/links.py:105` фильтрует по `pit_id` + `deleted_at` на каждом чтении; в `app/models/topology.py:66-85` индекса по `pit_id` нет |
| `gis.assets` | `(pit_id, deleted_at)` или партиальный `(pit_id) WHERE deleted_at IS NULL` | базовый фильтр всех выборок: `app/services/gis.py:221-226` |
| `gis.switching_ops` | `(pit_id, performed_at DESC)` | есть только `(asset_id, performed_at)`; журнал читается по `pit_id` (`app/services/state.py:130-138`) |
| `ops.defects` | `(pit_id, deleted_at)` | `app/services/defects.py:107`, дашборд `app/services/analytics.py:37-41` |
| `ops.media` | `(pit_id)`, `(asset_id, captured_at DESC) WHERE deleted_at IS NULL` | `app/services/media.py:119-126` |
| `ops.inspections` | `(pit_id, started_at DESC)` | `app/services/inspections.py:99-110`, экспорт |
| `ops.documents` | `(pit_id)` | `app/services/documents.py:126-132` |
| `ops.change_log` | не индекс, а политика ретенции/партиционирование | триггер пишет **полный** `to_jsonb(NEW)` на каждый INSERT/UPDATE/DELETE `gis.assets`, `gis.links`, `ops.defects` (`alembic/versions/0005_sprint5_sync.py:108-147`); чистки нет — таблица растёт неограниченно (и `GET /sync/pull` читает её же) |
| Поиск | `pg_trgm` GIN на `gis.assets.name/code`, `auth.employees.full_name/tab_no` | `ILIKE '%...%'` без индекса: `app/services/gis.py:243-244`, `app/api/routers/employees.py:85-88`, `app/api/routers/audit.py:38` |

### 2.4. Soft-delete: матрица и несоответствия

| Сущность | Удаление | Восстановление | Побочные данные |
|---|---|---|---|
| `gis.assets` | soft (`app/services/gis.py:495-517`), каскадно «архивирует» связи | да, `POST /assets/{id}/restore` (`app/services/gis.py:532-564`) | — |
| `gis.links` | soft (`app/services/links.py:241-247`) | да (`:250-289`, с проверкой живости концов и дублей) | — |
| `ops.defects` | soft (`app/services/defects.py:126-145`) | **нет** | фото остаются |
| `ops.media` | soft + **физическое удаление файла** (`app/services/media.py:136-146`) | нет — файла уже нет | противоречит soft-delete |
| `ops.documents` | soft + **физическое удаление файла** (`app/services/documents.py:152-162`) | нет — файла уже нет | то же противоречие |
| `gis.lines` | поле `deleted_at` есть (`app/models/topology.py:54`), API удаления нет | нет | «мертвая» модель |
| `ops.maintenance_entries` | **жёсткое** удаление (`db.delete`, `app/services/maintenance.py:66-71`) | нет | **без записи в аудит** |
| `gis.schema_snapshots` | иммутабельны, публикация фиксируется | — | корректно (`app/services/schema_snapshots.py:116-133`) |

Отдельно: `app/services/schema_blocks.py:48-53` (`_prune_ports`) удаляет порты, у которых есть связи; связи уходят каскадом БД (`ondelete="CASCADE"` в `app/models/topology.py:89-94`) — **молча, без аудита и без мягкого удаления**. Это единственное место, где схема теряет связи «сама собой».

Фильтр `deleted_at IS NULL` продублирован в 25+ запросах вручную; нет ни `with_loader_criteria`, ни ORM-хука — легко забыть, и в `app/services/defects.py:251-253` уже забыто: история объекта включает удалённые дефекты.

### 2.5. Пагинация и размеры выборок

| Endpoint | Ограничение | Риск |
|---|---|---|
| `GET /api/links` | **нет** limit/offset (`app/services/links.py:97-117`) | вся таблица связей в память |
| `GET /api/topology/graph` | «все объекты + связи» по определению | большой JSON на каждый рендер |
| `GET /api/assets` | `limit ≤ 1000`, default 500 (`app/api/routers/gis.py:159`) | ок |
| `GET /api/defects` | `limit ≤ 500`, default 100 (`app/api/routers/defects.py:42`) | ок, но `total = len(rows)` — не равен числу всех записей (`:52`) |
| `GET /api/employees`, `/api/audit` | limit + offset + честный `count` | образец для остальных |
| `GET /api/assets/{id}/moves`, `/maintenance`, `/documents` | только `limit`, без offset | мелочь |

Практика `total = len(rows)` (дефекты, связи, обходы, снимки, документы, перемещения, история) вводит фронтенд в заблуждение: `total` никогда не больше `limit`.

---

## 3. Безопасность

### 3.1. Покрытие авторизацией (сводка по 117 операциям)

| Тип охраны | Кол-во операций (оценка по grep) | Комментарий |
|---|---|---|
| `Depends(require_permission(...))` | ≈ 27 | 16 в `gis.py`, по 1-3 в `documents/defects/media/moves/reports/map_layers/employees/audit` |
| `Depends(require_admin)` | ≈ 25 | 13 в `gis.py`, 11 в `schema_blocks.py`, 1 в `defects.py` |
| Только `Depends(current_user)` | ≈ 52 | чтение + **мутации без права** (см. §3.2) |
| Публичные (по замыслу) | ≈ 13 | `auth` 7, `health` 2, скачивание файлов/отчётов по токену 4, `GET /` |

Механика прав корректна: `require_permission` (`app/api/deps.py:50-63`) сверяет код с `permissions_of(user)` и пишет `perm.denied` в аудит; `require_admin` (`:66-77`) отдельно логирует отказ. Набор кодов заведён в `backend-v2/seed.py:51-65` и разложен по ролям (`:67-79`).

### 3.2. Обход RBAC на офлайн-синхронизации — главная находка

`POST /api/sync/push` защищён только `current_user` (`app/api/routers/sync.py:17-27`), а внутри сервиса права проверяются «наполовину»:

```python
# app/services/sync.py:157-171
perms = permissions_of(actor)
allowed = (
    ALLOWED_ASSET_FIELDS
    if "asset.create" in perms
    else {"status", "grounded", "x", "y", "location_text"}
)
```

То есть пользователь **без** `asset.create` (например `viewer` или `contractor`) всё равно может через офлайн-очередь менять `status` (включено/отключено), `grounded` (заземление), координаты и `location_text` — при том что онлайн-аналоги требуют `asset.status.edit` (`app/api/routers/gis.py:287`), `asset.move` (`app/api/routers/moves.py:23`), `asset.create` (`:182`, `:257`). Дополнительно:

- `_apply_move` (`app/services/sync.py:197-274`) не проверяет ни `asset.move`, ни `check_bounds` — в отличие от `app/services/moves.py:30-77` и `app/services/ai_tools.py:136`;
- `_apply_defect_insert` (`app/services/sync.py:277-317`) не проверяет `defect.manage` (онлайн — `app/api/routers/defects.py:29`); `severity`/`category` не валидируются по `Literal`, потому что `patch` — свободный словарь (`app/schemas/sync.py:21`), и мусор в `severity` приведёт к нарушению CHECK-ограничения → 500 вместо 422;
- `entity_id` не сверяется с карьером: `db.get(Asset, op.entity_id)` без фильтра по `pit_id` (`app/services/sync.py:94`, `:201`, `:290`);
- запись `SyncOp` коммитится отдельно от применения операции (`:354-368`): при откате бизнес-операции идемпотентность фиксируется, а изменение — нет.

Для системы, где `status`/`grounded` — это электрическая безопасность, дыра в правах на офлайн-ветке **блокирует выпуск**.

### 3.3. Публичные точки доступа и IDOR

| Находка | Файл:строка | Суть |
|---|---|---|
| Подложка карты отдаётся **без аутентификации** | `app/api/routers/map_layers.py:92-105` | `GET /api/map/layers/{id}/image` не имеет ни `current_user`, ни токена; плюс `Cache-Control: public, max-age=86400`. Карта карьера уходит любому, кто знает UUID, и кэшируется прокси. |
| Тест **закрепляет** эту дыру | `tests/test_sprint12_api.py:51-52` | запрос образа без заголовков, `assert image.status_code == 200`. Тест придётся править вместе с фиксом. |
| Токены файлов не привязаны к сотруднику | `app/api/routers/media.py:110-129`, `app/api/routers/documents.py:67-87` | В JWT лежит `employee_id` (`app/core/security.py:145-162`), но при скачивании он **не сверяется** и статус сотрудника не проверяется: уволенный/заблокированный сохраняет доступ к файлу до 30 минут (`media` — 120 минут, `app/core/config.py:81`). Проверка `sub == media_id` есть — это хорошо, но привязки к субъекту мало. |
| Удаление фото — право `document.manage` | `app/api/routers/media.py:135-140` | «Админ» для медиа определяется наличием права на **документы**: `is_admin = "document.manage" in permissions_of(user)`. Роль с `media.create` без `document.manage` не удалит даже свои фото (авторство проверяется в `app/services/media.py:136-138`), а «документный» администратор удаляет любые. |
| Право `inspection.create` объявлено, но не проверяется | `backend-v2/seed.py:58`, `:73`, `:78` vs `app/api/routers/inspections.py:26-90` | Все 5 операций обходов используют только `current_user`: любой сотрудник (и `viewer`) может создавать обходы и отмечать результаты. |
| Межкарьерный доступ по id (задел на будущее) | `app/services/defects.py:119-123`, `app/services/inspections.py:113-122`, `app/services/gis.py:261-269` | `get_defect`/`get_inspection`/`get_asset` не фильтруют по `pit_id` (у `get_asset` параметр есть, но вызывается без него). Сейчас карьер один (`app/models/gis.py:31` — «в Спринте 2 один, но модель готова к нескольким»); при появлении второго это станет IDOR. |
| Обход другого сотрудника читается всеми | `app/api/routers/inspections.py:55-62` | `GET /api/inspections/{id}` без проверки владельца (запись — проверяется, `:73`, `:87`). Вероятно, допустимо для бригадного доступа, но решение нигде не зафиксировано. |

### 3.4. Валидация входных данных

| Место | Проблема |
|---|---|
| `app/schemas/sync.py:16-23` (`SyncOpIn.patch: dict[str, Any]`) | Свободный словарь: типы полей не проверяются, `severity`/`category` дефекта идут как есть (`app/services/sync.py:299-303`). |
| `app/api/routers/gis.py:449-460` (`switch_link`) | Тело запроса — `dict[str, Any]`, а не Pydantic-модель: `state` приводится `str(...)` и валидируется уже в сервисе (`app/services/state.py:113-114`), `reason` не ограничен по длине. Единственный такой endpoint среди мутаций. |
| `app/api/routers/documents.py:104-105` | `payload.doc_type` присваивается без проверки значения; при недопустимом значении — `CheckViolation` → 500 вместо 422. |
| `app/schemas/gis.py:98` (`attrs: dict[str, Any]`) | Свободные атрибуты валидируются самодельным валидатором (`app/services/gis.py:319-338`): только number/integer/boolean, без ограничения вложенности и объёма JSONB. |
| `app/services/sync.py:302` | `description` дефекта режется `[:2000]` молча, без ошибки. |
| `app/services/media.py:28-34` (`_parse_dt`) | Наивные даты принимаются: `datetime.fromisoformat("2026-01-01T10:00")` даст naive-время, которое затем сравнивается с timezone-aware в БД. |

Позитив: диапазоны и `Literal` в остальных схемах заданы аккуратно (`lat/lon`, `cores ≤ 64`, `count ≤ 200`, `section_size`, `expected_version`), лимиты загрузок ограничены (`MAX_DOCUMENT_MB`/`MAX_PHOTO_MB`/`MAX_LAYER_MB`).

### 3.5. Загрузка файлов

| Аспект | Состояние |
|---|---|
| Ограничение размера | есть: документы 25 МБ потоково с `unlink` при превышении (`app/services/documents.py:80-97`), фото 15 МБ, подложка 40 МБ |
| Path traversal | закрыт: имя файла не используется как путь (только `document_id`+суффикс, `app/services/documents.py:72-76`), `file_path` проверяет вхождение в корень (`:142-149`), `LocalStorage.path` — тоже (`app/services/storage.py:50-54`) |
| Проверка типа | **только по `Content-Type` от клиента**: `app/services/media.py:52-55`, `app/services/documents.py:64-70`. Magic bytes не проверяются, перекодирования нет (в отличие от подложек, где PIL всё перерисовывает в PNG, `app/api/routers/map_layers.py:64-74`) |
| **SVG-документы отдаются inline с того же origin** | `app/services/documents.py:20-32` разрешает `image/svg+xml`, а `app/api/routers/documents.py:82-87` отдаёт файл с `content_disposition_type="inline"` и `media_type` из БД. SVG — активный контент: сценарий внутри файла выполнится в origin приложения (CSP в `app/main.py:89-104` не выставляется). Загрузка требует `document.manage`, то есть это эскалация «оператор/админ → XSS против админа» |
| Прочее | `application/zip`/`docx` отдаются inline — браузер скачает, риск ниже; для `media` MIME от клиента сохраняется и затем отдаётся как есть (`app/services/media.py:64`, `:76`) |

### 3.6. JWT, cookie, 2FA

| Аспект | Состояние |
|---|---|
| Пароли | Argon2id 64 MiB/2 итерации (`app/core/security.py:29-35`), политика 10…128 символов + словарь распространённых + запрет табельного/ФИО (`:64-80`), `needs_rehash` (`:57-61`) — хорошо |
| Access-токен | HS256, 15 мин, `exp/sub/typ` обязательны (`app/core/security.py:106-115`), `typ` проверяется — хорошо |
| **Отзыв сессии не влияет на access-токен** | `current_user` (`app/api/deps.py:20-47`) не сверяет `sid` с `auth.sessions`: после logout/смены пароля/блокировки сотрудника ранее выданный access-токен живёт до 15 минут. Для «выкинуть немедленно» (инцидент, увольнение) этого мало |
| Refresh | непрозрачный, хранится HMAC-хэшем (`app/core/security.py:182-185`), ротация + детект повторного использования с окном на гонку вкладок (`app/services/auth.py:263-327`), cookie `HttpOnly`, `SameSite=Lax`, путь `/api/auth` (`app/api/routers/auth.py:46-55`) — хорошо |
| **`must_change` не принудителен** | флаг выставляется (`app/services/auth.py:686`) и отдаётся фронту (`:107`), но вход не блокируется: `login` (`app/api/routers/auth.py:86-130`) выдаёт полный access-токен. Админ `000001` из `seed.py:183-191` имеет пароль `admin` и **без 2FA** — фактически постоянная слабая учётная запись |
| 2FA | TOTP ±30 c, защита от replay по `last_counter` (`app/core/security.py:200-218`), секрет шифруется AES-GCM (`:227-236`), 10 резервных кодов хэшами (`app/services/auth.py:446-482`), отключение требует пароль+код (`:485-506`) — хорошо |
| **`EXPOSE_OTP_CODE` + `CONSOLE_NOTIFICATIONS` включены на стенде** | `backend-v2/.env` содержит `ENV=dev`, `EXPOSE_OTP_CODE=true`, `CONSOLE_NOTIFICATIONS=true`; в ответе `POST /api/auth/register/start` приходит `debug_code` (`app/services/auth.py:586`), а код печатается в лог `logger.warning` (`app/services/notify.py:48-53`) и в stdout (`:60-67`). На стенде в локальной сети (`PUBLIC_BASE_URL=http://192.168.31.87:5174`) это означает: любой, кто знает табельный номер незарегистрированного сотрудника (000003 в демо), забирает код и **задаёт ему пароль**. Плюс коды оседают в логах |
| CSRF | refresh-cookie `SameSite=Lax`, state-changing вызовы требуют `Authorization: Bearer` (не cookie) — риск низкий; отдельного CSRF-токена нет, но и cookie-аутентификации на мутациях нет |

### 3.7. Rate-limit

- Реализация — in-memory `SlidingWindowLimiter` (`app/core/rate_limit.py:14-38`), на процесс; при нескольких воркерах/репликах лимит умножается на их число. Для стенда приемлемо, для прода — Redis (интерфейс уже изолирован).
- **`client_ip` доверяет `X-Forwarded-For` безусловно** (`app/core/rate_limit.py:41-45`): клиент сам задаёт «свой» IP в заголовке, и лимитер считает его новым ключом. То же значение уходит в аудит (`app/api/middleware.py:28`), то есть подделывается и IP в журнале. Без доверенного прокси это обнуляет и rate-limit входа (`app/api/routers/auth.py:62-70`), и защиту от перебора.
- Не ограничены: `POST /auth/refresh` (`app/api/routers/auth.py:179-196`), `POST /auth/register/verify` (`:236-241` — 5 попыток на код, но новых кодов можно запросить до 20/час с IP, а лимит `X-Forwarded-For` обходится), `POST /auth/logout`.
- Есть: вход по IP+табельному (`:62-70`), MFA по сотруднику+IP (`:142-147`), регистрация по IP (`:225-230`).

### 3.8. Логирование секретов и секреты в коде

| Находка | Файл:строка |
|---|---|
| Пароль БД в дефолте конфига (реальный, не заглушка) | `app/core/config.py:26-28` (`postgresql+psycopg://karier_user:<redacted>@…`; после S-1 — заглушка, пароль только в `.env`) |
| Тот же пароль в тестовой обвязке | `tests/conftest.py:23-25` |
| Дефолтный `SECRET_KEY` в коде | `app/core/config.py:34` — при отсутствии `.env` JWT подписываются известным ключом; `app/main.py:58-59` только предупреждает и только при `ENV != prod` |
| OTP-коды в логах и stdout | `app/services/notify.py:48-53` (в `logger.warning` полный код), `:60-67` (баннер в stdout) |
| Код в ответе API | `app/services/auth.py:586` (`debug_code`) |
| Слабые seed-пароли | `seed.py:188` (`admin`), `:197` (`operator123`); тесты логинятся ими (`tests/conftest.py:111`, `tests/test_gis_api.py:25` и др.) |
| Пароль в коде графического admin-tool? | нет: `tools/db_admin.py:38` маскирует `password/hash/secret/token` при предпросмотре — хорошо |

Что хорошо: пароли и TOTP-секреты не попадают в аудит (в `payload` пишутся только метаданные), refresh-токен хранится хэшем, `problem_response` не отдаёт трейсбеков.

### 3.9. Прочее по безопасности

- **Заголовки безопасности** (`app/main.py:89-104`): `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: SAMEORIGIN`, `Permissions-Policy`, HSTS в prod — есть; **CSP отсутствует**, что и делает SVG-XSS (см. §3.5) выполнимым.
- **CORS**: `allow_credentials=True` при явном списке origin (`app/main.py:76-83`, `app/core/config.py:59`) — корректно; в `.env` стенда добавлен `http://192.168.31.87:5174` — стоит помнить, что это LAN-адрес.
- **Break-glass**: защищён от блокировки/увольнения/удаления/правки (`app/api/routers/employees.py:158-163`, `:201-206`, `:246-251`, `:318-323`), но **не защищён от `POST /employees/{id}/reset-password`** (`:357-369`) и `POST /employees/{id}/unblock` (`:341-354`) — администратор может перевыпустить пароль аварийной учётке, не используя сейф-процедуру `reset_break_glass.py`. Несогласованность инварианта.
- **MCP-сервер** (`mcp_server.py:28`, `102-110`): при `--http` поднимает SSE без какой-либо аутентификации и работает от служебной учётки `000001` (admin по умолчанию, `:28`), т.е. любой в сети получает инструменты создания связей и перемещения объектов. Для stdio-режима вопросов нет; для HTTP — обязателен токен/allowlist.
- **Аудит**: append-only на уровне БД (`alembic/versions/0001_sprint1_auth.py:230-238`), пишется отдельной сессией, чтобы фиксировать отказы и откаты (`app/api/middleware.py:51-59`, `app/services/audit.py:109-139`) — сильное решение. Минусы: (1) на **каждый** запрос, включая GET, открывается вторая сессия БД — при `pool_size=5, max_overflow=10` (`app/core/config.py:30-31`) это фактически 2 соединения на конкурентный запрос, т.е. ~7 одновременных запросов до таймаута пула; (2) при недоступности БД запись аудита теряется молча (`app/api/middleware.py:56-57` — `except: db.rollback()`), без fallback в файл и без метрики; (3) нет ретенции/партиционирования `audit.audit_log`.
- **Идентификаторы**: `app/core/ids.py` (25 строк) — заготовка, нигде не используется (UUID4 генерируются в моделях), мёртвый модуль.

---

## 4. Тестовые пробелы

### 4.1. Покрытие роутеров тестами (по обращениям к URL в `tests/*`)

| Роутер | Покрыт | Пробелы |
|---|---|---|
| `auth` | login, mfa/verify, register/* | **нет** `POST /auth/refresh`, `POST /auth/logout` |
| `me` | `GET /api/me` | **нет** `/me/sessions`, `/me/sessions/{id}`, `/me/mfa/totp/enroll|confirm|disable`, `/me/password` |
| `employees` | список, создание, правка, блокировка, увольнение, permanent | **нет** `reset-password`, `resend-invite`, `unblock` |
| `gis` (45 операций) | объекты, типы, связи, граф, снимки, layout, frame, pdf, groups(частично) | **нет** `/assets/{id}/maintenance` (GET/POST), `/maintenance/{id}` (DELETE), `/assets/{id}/ports/ensure`, `/assets/{id}/children` (есть в `test_line_builder`, но не как самостоятельный сценарий прав), `/topology/switching`, `/asset-groups`, `/asset-types` DELETE в части «тип используется» |
| `schema_blocks` | instantiate, cells, contours, legend, jumpers, line-equipment, bulk cells | **нет** `DELETE /schema/assets/{id}/place`, `POST /schema/assets/{id}/collapse`, partial-сценарии `_prune_ports` |
| `defects` | создание, список, карточка, правка, удаление, история | нет сценария «удалённый дефект исчез из статистики/истории» (см. §2.4 — он и не исчезает из истории) |
| `documents` | загрузка, список, скачивание, удаление (в `test_topology_api:224-250`) | **нет** `PATCH /documents/{id}`; нет проверки привязки токена к сотруднику |
| `media` | загрузка, список (в `test_ops_api`) | **нет** `GET /media/{id}/file`; **нет** `DELETE /media/{id}` — ни для автора, ни для администратора; нет теста на «чужое фото» |
| `map_layers` | загрузка, активная, отказ не-админу | **тест закрепляет публичность образа** (`tests/test_sprint12_api.py:51-52`) — это не пробел, а зафиксированная уязвимость |
| `moves` | через `/assets/{id}/move` в `test_sync_api` | нет проверки `check_bounds` при перемещении и нет отказа не-`asset.move` |
| `sync` | push (asset update + move), pull нет, conflicts, state | **нет** теста, что `viewer`/`contractor` не может менять `status` через push (главная дыра §3.2); нет `pull`-пагинации; нет конфликта «move stale» |
| `reports` | dashboard, token, export xlsx, битый токен | **нет** экспорта `passport` (PDF) и проверки «сотрудник уволен → токен не работает» |
| `inspections` | создание, отметки, submit | нет отказа без `inspection.create`, нет правки чужого обхода |
| `audit` | 1 проверка в `test_auth_api.py:145` | нет фильтров по датам/актёру, нет проверки append-only (что UPDATE/DELETE в БД запрещены) |
| `health` | `/health/ready` | `/health/live`, поведение при недоступной БД |

### 4.2. Сценарии, которые рискуют остаться незамеченными

1. **Права.** Проверки 403 есть в 9 файлах (в основном «оператор не может админское»), но **нет матричного теста** «роль × операция» и нет теста на офлайн-ветку. Любая новая мутация без `require_permission` пройдёт незамеченной.
2. **Soft-delete.** Восстановление покрыто только для `assets`/`links` (`tests/test_undo_restore.py`). Не покрыты: удаление дефекта и его исчезновение из дашборда/истории, удаление фото/документа (и что файл действительно недоступен), «удалённый объект не виден в графе/снимке».
3. **Миграции.** Нет теста «`alembic upgrade head` с нуля + `downgrade -1`»: 14 миграций с триггерами/функциями (`0001:230`, `0005:108-147`) никем не проверяются автоматически. Единственный способ узнать, что цепочка жива, — ручной прогон.
4. **Ограничения БД.** Check-констрейнты (`status`, `kind`, `severity`) дублируются в Pydantic, но не проверяются тестами «невалидное значение → 422, а не 500» (см. §3.4).
5. **Изоляция тестовой БД.** Хорошо: `tests/conftest.py:22-67` жёстко запрещает работать на не-`karier_test_db`. Плохо: фикстура `heal_topology` (`:70-100`) правит реальные строки эталонной схемы SQL-ом до каждого теста — тесты не изолированы транзакционно и зависят от конкретных кодов объектов (`BKRU1-IN1`, `KTP-14`). Любой тест, меняющий топологию, влияет на остальные.
6. **Слабые учётки в тестах.** Логин `000001/admin` (`tests/conftest.py:111`) и `000002/operator123` (`tests/test_gis_api.py:25` и др.) зашиты в 8 файлах: смена seed-пароля сломает половину набора.
7. **`tests/test_mcp_tools.py`** тестирует `ai_tools` напрямую, но HTTP-режим `mcp_server` (без аутентификации, §3.9) не покрыт ничем.

---

## 5. Топ-10 улучшений

Приоритет: `blocker` — до следующего выпуска, `high` — ближайший спринт, `medium` — планово, `low` — по возможности. Трудоёмкость: S ≤ 0.5 дня, M ≤ 2 дня, L > 2 дней.

| id | Severity | Файл:строка | Суть | Эффект | Трудоём. |
|---|---|---|---|---|---|
| B-01 | **blocker** | `backend-v2/app/api/routers/sync.py:17-27`; `backend-v2/app/services/sync.py:157-171`, `:197-205`, `:277-317` | `/sync/push` обходит RBAC: без `asset.create` можно менять `status`/`grounded`/координаты; move и defect-insert вообще без прав; `entity_id` без проверки карьера; типовая валидация patch отсутствует | Закрывает возможность несанкционированно снимать/подавать напряжение и перемещать объекты; закрывает обход прав через офлайн-очередь | S-M |
| B-02 | **high** | `backend-v2/app/services/auth.py:586`; `backend-v2/app/services/notify.py:48-53`; `backend-v2/app/core/config.py:85-87`; `backend-v2/.env` | `EXPOSE_OTP_CODE`/`CONSOLE_NOTIFICATIONS` включены: OTP уходит в HTTP-ответ (`debug_code`) и в лог. На стенде в LAN это захват регистрации любого незарегистрированного сотрудника | Убирает выдачу одноразовых кодов через API и логи; регистрация снова требует реального канала доставки | S |
| B-03 | **high** | `backend-v2/app/core/rate_limit.py:41-45`; `backend-v2/app/api/middleware.py:28`; `backend-v2/app/api/routers/auth.py:62-70` | `client_ip` доверяет `X-Forwarded-For` от клиента → обход rate-limit входа/регистрации/MFA и подделка IP в аудите | Восстанавливает смысл антибрутфорса и достоверность IP в журнале (брать IP только из доверенного прокси/`request.client`) | S |
| B-04 | **high** | `backend-v2/app/services/documents.py:20-32`; `backend-v2/app/api/routers/documents.py:82-87`; `backend-v2/app/main.py:89-104` | `image/svg+xml` разрешён и отдаётся `inline` с того же origin без CSP → хранимый XSS против администраторов; тип файла проверяется только по `Content-Type` | Убирает вектор XSS/кражи токенов через загруженный «документ»; добавляет CSP как второй барьер | S-M |
| B-05 | **high** | `backend-v2/app/api/routers/map_layers.py:92-105`; `backend-v2/tests/test_sprint12_api.py:51-52` | Подложка карьера отдаётся без аутентификации и кэшируется публично; тест это закрепляет | Закрывает утечку карты объекта любому в сети; тест приводится в соответствие | S |
| B-06 | **high** | `backend-v2/app/core/config.py:26-28`, `:34`; `backend-v2/tests/conftest.py:23-25`; `backend-v2/seed.py:188`, `:197` | Пароль БД и dev-`SECRET_KEY` — реальные значения в дефолтах кода; слабые seed-пароли; `must_change` не принудителен | Секреты уходят в ENV, дефолты становятся нерабочими, временный пароль реально требует смены | S |
| B-07 | medium | `backend-v2/app/services/topology.py:38-67`, `:139-201`; `backend-v2/app/services/state.py:46`, `:91-92`; `backend-v2/app/services/analytics.py:25`, `:70-97`; `backend-v2/app/services/defects.py:205-226`; `backend-v2/app/services/inspections.py:175-202` | Полный граф карьера считается 2-3 раза на переключение и на каждый рендер; N+1 в списках дефектов/обходов/снимков/перемещений | Снимает основной источник деградации latency и нагрузки на БД при росте реестра | M-L |
| B-08 | medium | `backend-v2/app/models/topology.py:66-85`; `backend-v2/app/models/ops.py:89-102`, `:133-149`; `alembic/versions/0005_sprint5_sync.py:108-147`; `backend-v2/app/services/gis.py:243-244` | Нет индексов по `pit_id`/`deleted_at` на links/assets/defects/media/inspections/documents; `ILIKE '%…%'` без trigram; `change_log` пишет полный снимок строки и не чистится | Ускоряет все списки, останавливает неограниченный рост журнала синхронизации | M |
| B-09 | medium | `backend-v2/app/api/deps.py:20-47`; `backend-v2/app/services/auth.py:686`, `:107`; `backend-v2/app/api/routers/auth.py:179-196`, `:236-241` | Access-токен не привязан к отзыву сессии (живёт до 15 мин после logout/блокировки); `must_change` не блокирует работу; `refresh`/`register/verify` без rate-limit | Управляемый инцидент-отзыв доступа и реальное принуждение смены пароля | S-M |
| B-10 | medium | `backend-v2/app/services/poles.py:124-187`; `backend-v2/app/services/composite.py:95-111`; `backend-v2/app/services/documents.py:152-162`; `backend-v2/app/services/media.py:136-146`; `backend-v2/app/services/maintenance.py:66-71` | Нет атомарности массовых операций (опоры/комплекты коммитятся поштучно); soft-delete фото/документа удаляет файл (восстановление невозможно); журнал ТО удаляется жёстко и без аудита | Устраняет «полупостроенные» линии и потерю файлов; приводит удаление к единой политике | M |

### Дополнительно (за пределами топ-10, но стоит зафиксировать)

| id | Severity | Файл:строка | Суть | Трудоём. |
|---|---|---|---|---|
| B-11 | medium | `backend-v2/app/api/routers/gis.py` (881 строка, 45 операций); `backend-v2/app/api/routers/employees.py`; `backend-v2/app/api/routers/gis.py:688-701` + `backend-v2/app/api/routers/documents.py:48-64` | «Божественный» роутер и дублирующийся (недостижимый) маршрут документов: разнести по доменным роутерам, логику — в сервисы | M |
| B-12 | medium | `backend-v2/app/api/routers/media.py:135-140`; `backend-v2/app/api/routers/inspections.py:26-90`; `backend-v2/seed.py:58` | Неверная привязка прав: удаление фото через `document.manage`, `inspection.create` объявлено но не проверяется | S |
| B-13 | medium | `backend-v2/app/api/routers/employees.py:341-354`, `:357-369` | Break-glass можно «обойти» через reset-password/unblock — инвариант «только через сейф-процедуру» не выдержан | S |
| B-14 | medium | `backend-v2/mcp_server.py:28`, `:102-110` | HTTP-режим MCP без аутентификации работает от admin-учётки | S |
| B-15 | medium | `backend-v2/app/api/routers/documents.py:104-105`; `backend-v2/app/api/routers/gis.py:449-460`; `backend-v2/app/schemas/sync.py:21` | Точечная невалидируемость: `doc_type` без проверки (500 вместо 422), `dict[str, Any]` в теле `switch_link`, свободный `patch` в синхронизации | S |
| B-16 | low | `backend-v2/app/services/defects.py:119-123`; `backend-v2/app/services/gis.py:261-269`; `backend-v2/app/services/inspections.py:113-122` | Нет фильтра по `pit_id` в `get_*` — задел на межкарьерный IDOR | S |
| B-17 | low | `backend-v2/tests/conftest.py:70-100` | Тесты мутируют эталонные строки общей тестовой БД (`heal_topology`) — хрупкость и взаимное влияние | M |
| B-18 | low | `backend-v2/app/services/gis.py:569-630`; `backend-v2/app/core/ids.py`; `backend-v2/app/services/gis.py:857-858` | Мёртвый код и заготовки, вводящие в заблуждение | S |

---

## 6. Рекомендованный порядок работ

**Шаг 0 (0,5-1 день, «до выпуска»)**
B-01 (RBAC на sync), B-02 (OTP), B-03 (XFF), B-04 (SVG + CSP), B-05 (подложка) — все дешёвые и все про безопасность. После них перезапустить `qa-runner`: «покраснеет» `tests/test_sprint12_api.py:51-52` (публичный образ) — это ожидаемый и правильный результат, тест нужно обновить вместе с фиксом.

**Шаг 1 (2-3 дня, «гигиена»)**
B-06 (секреты → ENV, принудительный `must_change`), B-09 (отзыв access-токена, rate-limit refresh/verify), B-12/B-13/B-14 (права и break-glass и MCP), B-15 (валидация границ), плюс индексные миграции из B-08.

**Шаг 2 (неделя, «производительность и целостность»)**
B-07 (кэш/инкрементальный граф + устранение N+1), B-10 (транзакционные границы), B-08 (ретенция `change_log`, trigram-поиск), B-17 (изоляция тестов), B-11 (разделение `gis.py`).

**Шаг 3 (планово)**
Матричные тесты «роль × операция», тест миграций с нуля, тест soft-delete матрицы, B-16, B-18.

---

## 7. Приложение: что именно проверялось и как

- Прочитаны все 61 файл `backend-v2/app/**`, 14 миграций, 26 файлов тестов, `seed.py`/`seed_*`/`mcp_server.py`/`tools/db_admin.py`, `requirements.txt`, `.env` (только имена и несекретные флаги: `ENV=dev`, `EXPOSE_OTP_CODE=true`, `CONSOLE_NOTIFICATIONS=true`, `COOKIE_SECURE=false`, `CORS_ORIGINS`, `PUBLIC_BASE_URL`).
- Числа (роутеры, операции, тесты, строки) получены статическим подсчётом декораторов/функций/строк; pytest не запускался, поэтому фактический pass/fail-статус набора здесь не утверждается.
- Оценки числа запросов в §2.2 — аналитические (по структуре вызовов), без профилирования на живой БД.
- Приоритеты выставлены по критерию «электрическая безопасность и утечка данных» → «стоимость запросов» → «удобство поддержки».
