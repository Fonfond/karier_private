# 05 — Ревью последних правок в рабочем дереве

Дата: 2026-11-24, 19:45–20:05 (локальное время машины, UTC+08:00).
Кто: `edit-reviewer` (роль — ревьюер правок команды `karier-improvements`).
Характер работ: **только чтение**. Код, тесты, конфиги и БД не изменялись, коммитов нет,
рабочая БД `karier_db` не открывалась, тесты не запускались (прогон трогает `karier_test_db`).

## Сводка (TL;DR)

| Показатель | Значение |
|---|---|
| Правок в отслеживаемых файлах | **19** (все — незакоммиченные, индекс совпадает с HEAD: staged = 0) |
| Новых файлов кода/тестов | **7** (`0014_schema_snapshots.py`, `schema_graph.py`, `schema_snapshots.py`, 4 теста) |
| Новых файлов фронтенда | **4** (`AddToSchemaPanel`, `SnapshotsPanel`, `BulkCellsDialog`, `vite.test.config.mjs`) |
| Новых документов | **8** (`docs/50…54`, `docs/team/01…03`) |
| Удалённых файлов | 0 |
| Файлов, отличающихся только переводами строк (CRLF↔LF) | **194** (шум при коммите) |
| Мусор без `.gitignore` | `backend-v2/venv.broken-20261123-0911/` — **8 120 файлов, ~207 МБ** |
| Секретов в правках | 1 новый случай реального пароля БД в отслеживаемом файле |
| Вердикт | Правки **функционально цельные и проходят проверки**, но **до коммита/деплоя нужны 6 обязательных исправлений** (см. §6) |

Самое важное в одном абзаце: набор изменений — это две законченные фичи («снимки схемы» с
публикацией и «визуальная сборка схемы/линии» с Undo/Redo через soft-delete+restore) плюс
косметика (русские тексты 422, индикация питания, валидация координат). Код синтаксически
корректен, typecheck/build по данным t3 зелёные, тесты (162) зелёные. Главные риски —
не в логике, а в **гигиене репозитория** (207 МБ битого venv без ignore, 194 файла CRLF,
реальный пароль БД в тестовом файле) и в **нескольких неатомарных составных операциях**
(undo/redo, кабель, пачка ячеек), которые при сбое оставляют частично применённое состояние.

## 1. Метод: как определены изменения (git недоступен)

`git` **не установлен** в системе: `where.exe git` → «Could not find files», каталогов
`C:\Program Files\Git`, `%LOCALAPPDATA%\Programs\Git`, `GitHubDesktop` нет. Поэтому `git status`,
`git diff` и `git diff --staged` выполнить нельзя. Состояние восстановлено прямым разбором
метаданных `.git` (только чтение, без запуска git):

1. разобран бинарный `.git/index` (v2, 412 записей) — пути, sha, размеры, mtime;
2. прочитано дерево HEAD (`refs/heads/feature/sprint-29-maintenance-cables` →
   `efd3cd2c…`, tree `2b97dbdc…`) с разрешением **и loose-, и packed-объектов**
   (`objects/pack/pack-a3bd2ae8….idx/.pack`, включая OFS/REF-delta) — 412 файлов, расхождений
   индекса с HEAD **нет**: staged = 0, удалённых = 0;
3. рабочее дерево сравнено с **содержимым blob'ов индекса** побайтово (а не по mtime) —
   19 файлов реально изменены, 194 отличаются только `\r\n`↔`\n`;
4. выполнен обход дерева (84 346 файлов) с фильтром по `.gitignore` — 20 неотслеживаемых
   файлов вне мусорных каталогов + 8 120 файлов в `venv.broken`;
5. для 19 изменённых файлов собраны unified-diff'ы из blob'ов индекса (108 КБ) — ревью
   велось по фактическим правкам, а не по догадкам;
6. синтаксис всех 18 изменённых/новых Python-файлов проверен `ast.parse` (без импортов и БД) — OK.

Ограничения метода: staged/unstaged разделены по индексу, а не по рабочей копии git; картина
актуальна на 24.11.2026 19:50. Отсутствие git — самостоятельный риск: зафиксировать правки
сейчас нечем, а при переустановке git с `core.autocrlf=true` 194 файла «исчезнут» из diff
(или наоборот — проявятся), см. R3.

## 2. Что именно сделано (группировка по смыслу)

### 2.1 Бэкенд: снимки схемы (Q-6), новая миграция

* `backend-v2/app/models/gis.py:247-271` — модель `SchemaSnapshot` (`gis.schema_snapshots`:
  `title`, `comment`, `status draft|published`, `JSONB payload`, автор/публикатор, CHECK, индекс).
* `backend-v2/alembic/versions/0014_schema_snapshots.py` — миграция: таблица + 2 индекса,
  FK на `gis.pits` (CASCADE) и `auth.employees` (SET NULL), `downgrade()` симметричен.
  Цепочка корректна: `0013_composite_types` → `0014_schema_snapshots`, других «голов» нет.
* `backend-v2/app/services/schema_graph.py` (новый) — сборка графа вынесена из роутера
  `GET /api/topology/graph` в сервис `build_graph_out()`; добавлен `build_snapshot_payload()`
  и `snapshot_counts()`. Диф роутера подтверждает: тело перенесено построчно, поведение
  сохранено, добавлен только контур (`attrs.block_code` без детей) в `blocks`.
* `backend-v2/app/services/schema_snapshots.py` (новый) — create/list/get/publish + аудит.
* `backend-v2/app/api/routers/gis.py:320-...` — 4 операции: `GET/POST /topology/snapshots`,
  `GET /topology/snapshots/{id}`, `POST /topology/snapshots/{id}/publish`.
* `backend-v2/app/models/__init__.py`, `app/schemas/gis.py:636+` — экспорт и контракты
  (`SnapshotCreate/Brief/Out/ListOut`).

### 2.2 Бэкенд: Undo/Redo — «архив и возврат»

* `services/gis.py:495-518` — `soft_delete` теперь **каскадно архивирует связи** удаляемого
  объекта (одна метка времени), чтобы в `GET /api/links` не оставались «одноконечные» связи.
* `services/gis.py:520-560` — `get_archived_asset()` + `restore_asset()`: возвращает объект и
  те связи, что ушли вместе с ним, но только если второй конец жив.
* `services/links.py:127` `get_link_any()` и `:250-292` `restore_link()` — возврат связи с
  проверками: не в архиве, порты существуют, оба объекта живы, нет активного дубля.
* `api/routers/gis.py:323-341`, `:471-...` — `POST /assets/{id}/restore`,
  `POST /links/{id}/restore` (права: `asset.delete` и `topology.edit`).

### 2.3 Бэкенд: визуальная сборка схемы и линии

* `services/schema_blocks.py:252-290` `_resolve_type()` — подбор активного типа-аналога вместо
  падения на отсутствующем `cell`.
* `:291-346` `create_contour()`, `:332` `unplace_from_schema()`, `:348` `place_on_schema()`.
* `:541-554` `_ensure_in_out()`, `:555-566` `_pick_port()`, `:568-628` `add_cells_bulk()`,
  `:630-672` `create_cable()`, `:674-...` `add_line_equipment()`.
* `:419-425` — последнюю ячейку контура удалять можно (для отмены Ctrl+Z).
* `api/routers/schema_blocks.py:110-210` — `POST /schema/contours`,
  `POST|DELETE /schema/assets/{id}/place`, `:209+` `POST /assets/{id}/cells/bulk`,
  `POST /assets/{id}/cables`, `POST /schema/line-equipment` (все — `require_admin`).
* `schemas/gis.py` — `ContourIn/Out`, `PlaceAssetIn`, `BulkCellsIn/Out`, `CellCableIn`,
  `LineEquipmentIn/Out`, `BlockCellIn.x/y` (опционально), `GraphBlockOut.kind/width/height`,
  `AssetTypeOut.is_composite/composite_template`.

### 2.4 Бэкенд: сообщения валидации и конфиг

* `app/main.py:34-40` — `reconfigure(encoding="utf-8")` для stdout/stderr (Windows cp866).
* `app/main.py:107-190` — `FIELD_LABELS` + `_ru_validation_message()` + переписанный
  обработчик `RequestValidationError`: русский текст, «и ещё N», WARNING-лог с методом/путём.
* `app/models/auth.py:112-131` — `passive_deletes=True` для `credential`, `mfa_factors`,
  `sessions` (+ `delete-orphan` у сессий): причина — каскад делает БД, а SQLAlchemy падал на NOT NULL.
* `backend-v2/requirements.txt` — `openpyxl==3.1.5`, `reportlab==5.1.0`, `pillow==13.0.0`
  (импортируются в `services/reports.py`, `services/schema_pdf.py`, `routers/map_layers.py`;
  в venv стоят ровно эти версии — проверено `importlib.metadata`).

### 2.5 Тесты

* `tests/conftest.py:1-150` — жёсткая изоляция тестовой БД: подмена `DATABASE_URL` до импорта
  приложения + три fail-fast проверки, что база именно `karier_test_db`; `operator_secret`
  теперь **читается из БД** (расшифровка TOTP-секрета оператора `000002`), а не берётся константой.
* Новые модули: `test_schema_snapshots.py` (публикация, неизменяемость, RBAC),
  `test_schema_builder.py` (контур/постановка/ячейки/перемычка), `test_line_builder.py`
  (пачка ячеек, кабель, КТП в линии, RBAC), `test_undo_restore.py` (удаление/возврат объекта и связи).

### 2.6 Фронтенд

* `components/map/SnapshotsPanel.tsx`, `AddToSchemaPanel.tsx`, `BulkCellsDialog.tsx` (новые) —
  панель снимков (создать/открыть/опубликовать/скачать JSON), добавление на схему (из реестра,
  по типу, контуром, оборудование линии), пачка ячеек с секциями.
* `components/map/SchemaView.tsx` — обобщённая история (позиции + серверные команды undo/redo),
  горячие клавиши Ctrl+Z/Ctrl+Y, режим «Кабель», панели, контуры (`block.kind`), секции ячеек,
  цвета питания.
* `lib/gis.ts` — `POWER_COLOR`, типы снимков, новые вызовы API (`restoreAsset`, `restoreLink`,
  `createContour`, `placeOnSchema`, `unplaceFromSchema`, `addBlockCellsBulk`, `createCellCable`,
  `addLineEquipment`, `snapshots/createSnapshot/snapshot/publishSnapshot`).
* `pages/RegistryPage.tsx` — предвалидация формы (длина, парность координат, границы карты).
* `pages/DashboardPage.tsx`, `pages/MapPage.tsx` — подписи/легенда.
* `auth/AuthProvider.tsx` — `SESSION_HINT` в localStorage, чтобы первый визит не давал 401 в консоли.
* `vite.config.ts:11` — `host: '0.0.0.0'` (доступ с телефона по LAN).

### 2.7 Документы

`docs/50-tz-as-built-and-report.md/.docx` (ТЗ «как реализовано», v1.4, 162 теста / 117 операций —
сходится с t3 и `docs/54`), `51-schema-snapshots-report.md`, `52-schema-builder-report.md`,
`53-line-builder-report.md`, `54-deploy-guide.md` (18 КБ: дерево проекта, `.env`, systemd, nginx,
чек-лист перед публикацией) + `docs/team/*` (отчёты команды).

## 3. Таблица рисков

Серьёзность: **В** — высокий, **С** — средний, **Н** — низкий, **И** — информация.

| ID | Сер. | Файл:строка | Что грозит | Минимальная правка |
|---|---|---|---|---|
| R1 | **В** | `backend-v2/tests/conftest.py:24` | Реальный пароль БД `karier_user` (`…:<redacted>@…`; сам пароль — в `.env`, в репозитории его нет) попал в **отслеживаемый** файл; тот же пароль уже есть в `app/core/config.py:27`, `scripts/smoke.ps1:68,171`, `docs/52:91`, `.env` (в ignore). У `origin` — публичный GitHub (`github.com/Fonfond/karier-app`): push = утечка пароля к рабочей БД. | Не хранить пароль в коде: `DEFAULT_TEST_URL` собрать из `os.environ["TEST_DB_USER"]/["TEST_DB_PASSWORD"]`, при отсутствии — fail-fast с подсказкой. Отдельно (вне правок): ротация пароля `karier_user` + вычистка из `config.py`, `smoke.ps1`, доков. |
| R2 | **В** | `.gitignore:5` (+ каталог `backend-v2/venv.broken-20261123-0911\`) | Шаблон `backend-v2/venv/` не покрывает `venv.broken-*`: **8 120 файлов, ~207 МБ** битого venv видны как untracked. `git add -A` закоммитит бинари (`python.exe`, DLL) и раздувает репозиторий необратимо. | Добавить в `.gitignore` строку `backend-v2/venv*/` (или `venv.broken*`) **и** удалить сам каталог вручную; перед коммитом сверять `git status --porcelain`. |
| R3 | **В** | `.gitattributes` (нет) / `.git/config:1-6` | 194 отслеживаемых файла отличаются от индекса **только** CRLF↔LF (71 в `backend-v2`, 49 в `src-v2`, 29 в `src`, 20 в `docs`). `core.autocrlf` не задан, `.gitattributes` отсутствует → они попадут в коммит как изменения и полностью замаскируют 19 реальных правок. | Создать `.gitattributes`: `* text=auto eol=lf` (плюс `*.ps1 text eol=crlf`, `*.cmd text eol=crlf`); затем `git add --renormalize .` одним отдельным коммитом «normalize line endings». |
| R4 | **С** | `backend-v2/tests/test_schema_builder.py:93` | В комментарий попал литерал `\n`: `# … и блоком\n    assert any(node["id"] == contour["id"] …)` — утверждение оказалось **внутри комментария** и не выполняется. Тест зелёный, но проверка «контур есть и в nodes» мертва; тот же механический сбой мог задеть другие файлы. | Разбить на две строки: комментарий и `assert any(...)` отдельно; перечитать диффы на другие `\n`-склейки (проверено — в Python-файлах изменений больше нет). |
| R5 | **С** | `backend-v2/app/main.py:157` | Изменён **контракт** problem+json: ключи `fields` были путями полей (`name`, `type_code`, `lat`), стали русскими подписями (`Название`, `Тип`, `Широта`). Единственный тест, фиксирующий контракт, — `test_gis_api.py:149` (`power_kw`) — проходит случайно, потому что этой подписи нет в `FIELD_LABELS`. Любой клиент, ключующийся по имени поля, тихо ломается. | В `fields` оставить машинные ключи, подписи отдавать рядом: `fields[key] = message`, `field_labels[key] = label`; `FIELD_LABELS` применять только к тексту `detail`. Добавить тест на ключи `fields`. |
| R6 | **С** | `src-v2/src/components/map/SchemaView.tsx:1205-1235` (+ `:949-984`, `:867-899`, `:986-1020`) | Undo/Redo серверных команд **не атомарен**: одна запись истории = несколько последовательных запросов («установка блока» — N удалений детей + корень; «оборудование линии» — связь + объект). При сбое середины часть действий уже применена, а `historyIndex` не сдвигается → повторный Ctrl+Z даёт 404/409, состояние клиента и БД расходятся. Плюс отмена удаления ячейки создаёт **новый** id (`addBlockCell`), т.е. «тот же» элемент получает другой код. | Минимум: в `runHistory` выполнять шаги идемпотентно (игнорировать 404 при удалении уже удалённого), при частичном сбое — не блокировать историю и показывать «применено частично». Правильно: один batch-эндпоинт (`POST /schema/commands`) с одной транзакцией. |
| R7 | **С** | `backend-v2/app/services/schema_blocks.py:630-672`, `:674-...`, `:541-554` | `create_cable()` и `add_line_equipment()` — составные операции без общей транзакции: `_ensure_in_out` коммитит порты, затем создаётся объект, затем связь. Если связь/объект отвалится (валидация направления, 409, обрыв) — остаются **сироты**: новые порты `IN-1/OUT-1` и/или объект в реестре без связи, клиент получает 5xx. | Заменить внутренние `db.commit()` на `db.flush()` и коммитить один раз в конце; при исключении — `db.rollback()`. |
| R8 | **С** | `backend-v2/app/services/schema_blocks.py:568-628` | `add_cells_bulk` создаёт до 200 ячеек, и каждая идёт через `gis.create_asset` с **собственным commit**. При сбое на середине в БД остаётся частичная пачка, при этом запись в истории Undo не создаётся (клиент получил ошибку) → пользователь чистит руками. Время ответа линейно растёт по числу коммитов. | Один commit на всю пачку (`flush` внутри цикла), лимит `count` снизить до 50 либо сделать операцию «всё или ничего». |
| R9 | **С** | `backend-v2/app/services/gis.py:532-560` | `restore_asset()` не проверяет **родителя**: можно вернуть ячейку/ребёнка, чей блок/группа остались в архиве. В реестре и в графе появляется висячая иерархия (`parent_asset_id` → архивный объект); `schema_graph` такие ячейки просто не покажет. | Перед восстановлением: если `asset.parent_asset_id` указывает на архивный объект — `409 asset.parent_archived` (или восстанавливать каскадом, как связи). |
| R10 | **С** | `backend-v2/app/services/schema_snapshots.py:62` | `title=payload.title.strip()` выполняется **после** `min_length=2`: заголовок `"  "` проходит валидацию и сохраняется пустым (`title=""`), снимок получает безымянное имя в списке. | Валидировать после strip: `title: str = Field(min_length=2)` + `@field_validator("title")`, либо проверка в сервисе с `ApiError(400, "schema_snapshot.title_empty")`. |
| R11 | **С** | `backend-v2/app/services/schema_graph.py:171-196`, `models/gis.py:267` | В `payload` пишется **полный** слепок (все узлы, порты, связи, блоки, рамка): на текущих демо-данных это десятки КБ, на боевом объёме — мегабайты на снимок, без лимита, ретенции и без ограничения числа снимков. `GET /snapshots/{id}` отдаёт всё это синхронно; БД растёт неограниченно. | Добавить лимит (`max_snapshots` на pit / размер `payload`), периодическую чистку черновиков, и отдавать `payload` только по явному запросу (`?with_payload=true`). |
| R12 | **С** | `src-v2/vite.config.ts:11` | `host: '0.0.0.0'` делает dev-сервер и прокси `/api` доступными всей локальной сети, по HTTP, с cookie refresh-токена (`COOKIE_SECURE=false` в стендовом `.env`). Для «посмотреть с телефона» это удобно, но это постоянная настройка по умолчанию, а не разовая. | Вынести в отдельный конфиг (`vite.config.lan.ts`) или включать через `process.env.LAN === '1'`; в обычном `npm run dev` оставить `127.0.0.1`. |
| R13 | **С** | `src-v2/src/components/map/SchemaView.tsx:2011` | `canPublish={canEdit}`, а публикация на бэке требует **admin**; `canEdit` приходит из `MapPage.tsx:701` как `can('settings.edit')`. Сегодня совпадает (обе — только admin), но при выдаче `topology.edit` пользователь увидит «Опубликовать»/«Сделать снимок» и получит 403. Текст панели («снимок делает администратор», `SnapshotsPanel.tsx:142`) противоречит бэку, где create = `topology.edit`. | Прокинуть явный признак `isAdmin` (из `user.role`) в `canPublish` и разделить тексты: «создать снимок» — право правки топологии, «опубликовать» — администратор. |
| R14 | **С** | `backend-v2/app/api/routers/schema_blocks.py:119,152,167,222,264,293` | Новые операции закрыты `require_admin`, тогда как вся остальная модель прав построена на permission-кодах (`asset.create`, `topology.edit`). Итог: роль с `topology.edit` может двигать раскладку (`PUT /topology/layout`), но не может поставить объект на схему, нарисовать контур или повесить кабель — «редактор без правок». | Привести к модели прав: `place`/`unplace` → `topology.edit`; `contours`, `cells/bulk`, `cables`, `line-equipment` → `asset.create` (+`topology.edit`). |
| R15 | **Н** | `backend-v2/tests/conftest.py:122-150`, `test_undo_restore.py:33`, `test_schema_snapshots.py:79`, `test_line_builder.py:93` | Тесты жёстко зависят от seed: непустой граф, существующая опора, оператор `000002` с **подтверждённой** 2FA в тестовой БД (секрет теперь читается из БД). На «чистой» `karier_test_db` прогон падает до тестов с RuntimeError — это осознанный fail-fast, но он делает набор несамодостаточным. | Фикстура-seed (создаёт пит/опору/оператора с TOTP внутри теста) или отдельный `pytest.ini`-маркер `needs_seed` + понятная инструкция в `backend-v2/README.md`. |
| R16 | **Н** | `docs/54-deploy-guide.md:161`, `tests/test_schema_builder.py:209`, `test_line_builder.py:193`, `test_schema_snapshots.py:109`, `test_undo_restore.py:19` | Пароль оператора `operator123` зафиксирован в коде тестов и в гайде. Если этот пароль останется на стенде/боевом контуре — он по сути публичный. | В `seed.py` генерировать пароль и печатать в консоль (как сделано для аварийной учётки `000000`); в тестах брать его из фикстуры/переменной окружения. |
| R17 | **Н** | `backend-v2/tests/test_line_builder.py:83-84` | Мёртвый код: `for cell in body["items"] if "body" in dir() else []: pass` — цикл, который ничего не делает; при падении выше `body` не определён, и уборка не выполняется. | Удалить две строки; уборку делать через `try/finally` с `body = None` заранее. |
| R18 | **Н** | `backend-v2/tests/test_schema_snapshots.py:103` | Проверяется несуществующий маршрут: `POST /api/topology/snapshots/publish` даёт 405 (путь совпадает с `GET /{snapshot_id}`), т.е. тест подтверждает «метод не тот», а не защиту публикации. | Удалить строку — реальная проверка публикации есть в `:126` (`test_publish_requires_admin_role`). |
| R19 | **Н** | `backend-v2/alembic/versions/0014_schema_snapshots.py:53-58` vs `app/models/gis.py:255-258` | Миграция создаёт индекс `ix_schema_snapshots_created`, в модели он не объявлен → следующий `alembic revision --autogenerate` предложит его удалить (дрейф схемы). | Добавить `Index("ix_schema_snapshots_created", "created_at")` в `__table_args__` модели. |
| R20 | **Н** | `src-v2/vite.test.config.mjs` (новый) | Файл не подключён ни к одному npm-скрипту (`package.json:11` — только `vitest run`), при этом поднимает **dev-сервер** 5175→8002, а не тесты. Мёртвый конфиг со временем разъедется с `vite.config.ts`. | Либо добавить скрипт `"dev:testapi": "vite --config vite.test.config.mjs"` (и упомянуть в `src-v2/README.md`), либо убрать файл из дерева. |
| R21 | **Н** | `docs/50-tz-as-built-and-report.docx` (70 КБ) | Бинарный документ лежит рядом с md-источником: при любой правке md `.docx` надо пересобирать вручную, иначе версии расходятся; git не покажет дифф. | Держать `.docx` вне репозитория (releases/папка `C:\karier\docs-out`), а в `docs/README.md` — одну команду генерации. |
| R22 | **Н** | `backups/karier_before_clean_20261109.dump` (372 МБ), `backups/karier_user_data_20261110.dump` (371 МБ) | Дампы **рабочей** БД лежат внутри проекта (сейчас корректно игнорируются `.gitignore`), но содержат реальные данные и хеши паролей: `git add -f`, смена правил ignore или архивирование папки вынесут их наружу. | Перенести в `C:\karier\backups` (вне репозитория), в `.gitignore` оставить правило `backups/`, в `docs/54` — путь вне проекта. |
| R23 | **Н** | `backend-v2/app/main.py:34-40` | `sys.stdout.reconfigure()` на **импорте** приложения меняет глобальные потоки процесса: под uvicorn/systemd это влияет и на чужие хендлеры, а при уже перенаправленном потоке ошибка тихо глотается — то есть эффект «вроде есть, а в проде нет». | Настраивать только свой `StreamHandler` с `encoding="utf-8"` в `logging.basicConfig` (или вынести под `if settings.ENV == "dev"`). |
| R24 | **Н** | `backend-v2/app/main.py:160-167` | Каждый 422 пишется в WARNING с методом/путём/`content-length`: при потоке невалидных запросов это шум в `api.log` и дешёвый способ раздуть лог. В лог не попадают значения полей — утечки нет. | Понизить до INFO (или логировать только код ошибки) + положиться на `core/rate_limit.py`. |
| R25 | **Н** | `src-v2/src/pages/MapPage.tsx:834-835` | Цвета питания захардкожены (`#F04438`, `#22C55E`) вместо `POWER_COLOR` из `lib/gis.ts`: при смене палитры легенда карты разъедется со схемой. | `import { POWER_COLOR } from '../lib/gis'` и подставить в `style`. |
| R26 | **Н** | `src-v2/src/components/map/SchemaView.tsx:303` | `key={cell.id}` стоит и на `<Fragment>`, и на вложенном `<div>` — дублирование ключа; при рефакторинге легко получить предупреждение React о ключах. | Оставить `key` только у `<Fragment>`. |
| R27 | **Н** | `src-v2/src/pages/DashboardPage.tsx:230` | Подпись «Мачты Освещения Мобильные» — каждое слово с заглавной и обратный порядок; рядом стоит «мобильных». В интерфейсе выглядит как ошибка. | «Мобильные мачты освещения». |
| R28 | **Н** | `backend-v2/app/services/schema_blocks.py:555-566` | `_pick_port` при отсутствии порта нужного `kind` молча берёт `ports[0]` → кабель может соединить «выход с выходом», и в графе появится электрически бессмысленная связь (проверки `links_service` пропустят, т.к. формально всё валидно). | Если подходящего `kind` нет — `ApiError(422, "link.port_kind_mismatch", …)` вместо фолбэка. |
| R29 | **Н** | `backend-v2/app/api/routers/gis.py:330` | Восстановление объекта требует право **`asset.delete`** (симметрично удалению). Логично, но означает: тот, кто удалять не может, не может и отменить чужое удаление — при этом кнопка Undo есть у любого редактора схемы. | Осознанно оставить (документировать в `docs/54`) или ввести `asset.restore`, выдав его редакторам топологии. |
| R30 | **Н** | `backend-v2/app/services/links.py:250-292` | `restore_link` проверяет дубль только в направлении `from→to`; активная связь `to→from` (обратная пара) не обнаруживается и восстановление создаст «двойную» связь между теми же портами. | Проверять оба направления (`or_(and_(from==x, to==y), and_(from==y, to==x))`). |
| R31 | **И** | `backend-v2/tests/conftest.py:23-27` | Комментарий/поведение: `TEST_DATABASE_URL` по умолчанию содержит хост и **имя пользователя** рабочей БД (`karier_user`) — тесты формально ходят под той же ролью, что и прод (различие только в имени базы). Права роли на `karier_db` остаются, т.е. защита — только проверка имени базы в conftest. | Отдельная роль `karier_test` с правами только на `karier_test_db`. |
| R32 | **И** | репозиторий в целом | В HEAD **уже отслеживаются** артефакты: `backend/app/__pycache__/*.pyc` (6 файлов), `.vs/*` (6), `.vercel/*` (2) — всего 412 файлов индекса = 412 файлов HEAD. `.gitignore` на них не действует, пока файлы в индексе — предсуществующая проблема, но именно она усиливает R2/R3. | Отдельным коммитом `git rm -r --cached backend/app/__pycache__ .vs .vercel` (+ `--cached` для `*.pyc`), затем проверить `git status`. |
| R33 | **И** | `git` отсутствует в PATH | Правки нельзя ни зафиксировать, ни откатить; `git status/diff` недоступны. Это также объясняет, почему в индексе LF, а в рабочем дереве CRLF. | Установить Git for Windows и сразу задать `core.autocrlf`/`.gitattributes` (R3) до первого коммита. |
| R34 | **И** | `src-v2/src/auth/AuthProvider.tsx:21,32-42` | `SESSION_HINT` в localStorage: после потери storage (очистка, приватный профиль) при живой cookie пользователь получает лишний экран входа — осознанный компромисс ради чистоты консоли. Отзыв сессии обрабатывается (`refresh` → 401 → hint снимается). | Принять как есть; при желании — keep-alive `GET /auth/me` вместо флага. |

## 4. Проверки, которые прошли (можно принять как есть)

* **Миграция 0014** — цепочка `0013_composite_types` → `0014_schema_snapshots` непрерывна,
  вторых «голов» нет; `downgrade()` зеркален `upgrade()`; FK `ON DELETE CASCADE` для `pit_id`,
  `SET NULL` для авторов; CHECK на `status` совпадает с моделью. Миграция аддитивная — на
  существующие таблицы не влияет.
* **`passive_deletes=True`** (`app/models/auth.py:112-131`) — обоснован: в `0001_sprint1_auth.py`
  все дочерние FK (`credentials:135`, `mfa_factors:153`, `sessions:189`) объявлены `ON DELETE CASCADE`,
  поэтому SQLAlchemy корректно перестаёт трогать детей при удалении сотрудника.
* **Вынос `build_graph_out`** в `services/schema_graph.py` — построчное сравнение с прежним телом
  роутера: порядок полей, фильтры `schema_block_id is None`, сборка блоков/перемычек сохранены;
  добавление контуров в `blocks` — единственное расширение, и оно закрыто тестом
  (`test_schema_builder.py:88-92`).
* **Обратная совместимость API** — все изменения контрактов аддитивные: новые эндпоинты,
  новые необязательные поля (`GraphBlockOut.kind/width/height`, `BlockCellIn.x/y`,
  `AssetTypeOut.is_composite`). Ломающее изменение одно — ключи `fields` в 422 (R5).
* **`requirements.txt`** — закреплённые версии (`openpyxl==3.1.5`, `reportlab==5.1.0`,
  `pillow==13.0.0`) реально установлены в `backend-v2/venv` и импортируются продовым кодом
  (`services/reports.py`, `services/schema_pdf.py`, `routers/map_layers.py`). Синтаксис всех
  18 изменённых/новых Python-файлов корректен (`ast.parse`).
* **Русские сообщения валидации, индикация питания, предвалидация формы реестра** — согласованы
  с бэкендом (лимит 255 символов, парность/границы координат), к ним претензий нет.
* **Заявленные в документах цифры** — `docs/50` (162 теста, 117 операций API) сходятся с
  QA-базлайном t3 (162 passed) и `docs/54` (117 операций), т.е. документы не выдают желаемое
  за сделанное.
* **Фронтенд** — по данным t3 `tsc -b --noEmit` и `vite build` зелёные (exit 0, 508 модулей),
  `vitest` 6 тестов passed; повторно не запускал, чтобы не дублировать и не трогать БД.

## 5. Чего я не делал

* **Не запускал pytest**: набор обращается к `karier_test_db` и оставляет в ней данные —
  ограничение задачи «БД не трогать». Зелёный прогон на этом дереве уже зафиксирован в t3.
* **Не запускал `tsc`/`vite build`/`vitest`** — те же проверки в t3 на этом же дереве (код не
  менялся с момента снятия базлайна; mtime файлов это подтверждает).
* **Не открывал БД** ни одним запросом (включая read-only) — состояние схемы оценивал статически
  по миграциям и моделям.
* **Не менял код, конфиги и тесты**, не делал коммитов, не ставил/не удалял пакеты, не запускал
  `test-db-reset.cmd`, не перезапускал стек.

## 6. Итог: что делать

### 6.1 Обязательно до коммита/деплоя (6 пунктов)

1. **R1** — убрать реальный пароль БД из `tests/conftest.py:24` (брать из окружения),
   запланировать ротацию пароля `karier_user` и вычистку из `app/core/config.py:27`,
   `scripts/smoke.ps1`, `docs/52`. Пока пароль в репозитории — **не пушить в `origin`**.
2. **R2** — `.gitignore`: `backend-v2/venv*/` (или `venv.broken*`) + удалить сам каталог
   (207 МБ, 8 120 файлов) до `git add -A`.
3. **R3** — `.gitattributes` с `* text=auto eol=lf` (+ `*.ps1`/`*.cmd` как `crlf`) и один
   отдельный «renormalize»-коммит: иначе в диффе будут 194 файла переводов строк вместо 19 правок.
4. **R5** — вернуть машинные ключи в `fields` (422), подписи — отдельным полем; добавить тест
   на ключи. Сейчас это единственное ломающее изменение контракта.
5. **R4** — починить `test_schema_builder.py:93` (утверждение съедено литералом `\n`).
6. **R9, R10** — `restore_asset` должен отказывать при архивном родителе; `SnapshotCreate.title`
   валидировать после `strip()`. Оба — по 3–5 строк, но именно они дают «странные» данные в UI.

### 6.2 Сразу после деплоя / следующий спринт

* **R6, R7, R8** — атомарность: batch-эндпоинт для undo/redo, `flush` вместо `commit` в
  `create_cable`/`add_line_equipment`, одна транзакция на пачку ячеек.
* **R11** — ретенция и лимит снимков (payload в JSONB растёт неограниченно).
* **R14, R13** — привести права новых эндпоинтов к permission-модели и разделить
  «создать снимок» / «опубликовать» в UI.
* **R19** — дрейф индекса в модели снимков (для чистого `--autogenerate`).
* **R15, R16, R17, R18** — тестовая гигиена: seed-фикстура, пароли из окружения,
  мёртвый код и «тест не того маршрута».
* **R32, R33** — почистить индекс от `__pycache__`/`.vs`/`.vercel`, поставить git и
  зафиксировать правки; **R22** — вынести дампы БД за пределы проекта.

### 6.3 Можно принять как есть

Русские тексты 422 (с оговоркой R5), `POWER_COLOR` и легенда, предвалидация формы реестра,
`SESSION_HINT` (R34), `passive_deletes`, миграция 0014, вынос графа в сервис, закреплённые
версии `requirements.txt`, тексты документов (цифры сходятся с базлайном), мелкие огрехи
R24–R27 — косметика, не блокирует.

## 7. Приложение: перечень изменений

**Изменено (19, все — незакоммиченные):**
`backend-v2/app/api/routers/gis.py`, `.../routers/schema_blocks.py`, `backend-v2/app/main.py`,
`backend-v2/app/models/__init__.py`, `.../models/auth.py`, `.../models/gis.py`,
`backend-v2/app/schemas/gis.py`, `backend-v2/app/services/gis.py`, `.../services/links.py`,
`.../services/schema_blocks.py`, `backend-v2/requirements.txt`, `backend-v2/tests/conftest.py`,
`src-v2/src/auth/AuthProvider.tsx`, `src-v2/src/components/map/SchemaView.tsx`,
`src-v2/src/lib/gis.ts`, `src-v2/src/pages/DashboardPage.tsx`, `src-v2/src/pages/MapPage.tsx`,
`src-v2/src/pages/RegistryPage.tsx`, `src-v2/vite.config.ts`.

**Новое (20 вне мусорных каталогов):**
`backend-v2/alembic/versions/0014_schema_snapshots.py`, `backend-v2/app/services/schema_graph.py`,
`backend-v2/app/services/schema_snapshots.py`, `backend-v2/tests/test_schema_builder.py`,
`test_line_builder.py`, `test_schema_snapshots.py`, `test_undo_restore.py`,
`src-v2/src/components/map/AddToSchemaPanel.tsx`, `BulkCellsDialog.tsx`, `SnapshotsPanel.tsx`,
`src-v2/vite.test.config.mjs`, `docs/50-tz-as-built-and-report.md/.docx`, `docs/51..54-*.md`,
`docs/team/01-backend-audit.md`, `02-frontend-audit.md`, `03-qa-baseline.md`
(последние три — отчёты этой команды).

**Мусор, требующий внимания:** `backend-v2/venv.broken-20261123-0911/` — 8 120 файлов, ~207 МБ,
не покрыт `.gitignore`.

**Игнорируется корректно (но лежит в проекте):** `backups/*.dump` (2 × ~372 МБ),
`.tmp/` (chrome-профили, 37 МБ каждый), `.npm-cache/`, `.venv/`, `venv/`, `node_modules/`,
`backend-v2/.env`, `backend-v2/var/media/`.
