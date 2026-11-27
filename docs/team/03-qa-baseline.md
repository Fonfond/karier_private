# 03 — QA-базлайн: pytest, tsc, vite build

Дата снятия: 2026-11-24, 19:26–19:41 (локальное время машины, UTC+08:00).
Кто: `qa-runner` (роль — QA-инженер команды `karier-improvements`).
Характер работ: только измерения. Код, тесты, конфиги и рабочая БД `karier_db` не изменялись,
рабочий стек не перезапускался, тестовая БД не сбрасывалась.

## Сводка (TL;DR)

| Проверка | Команда | Результат | Время | Вердикт |
|---|---|---|---|---|
| Бэкенд-тесты, прогон 1 | `python -m pytest -q` (backend-v2) | **162 passed, 0 failed, 0 skipped**, 541 warning | 230.84 s (3:50) | ✅ зелёный |
| Бэкенд-тесты, прогон 2 (повтор) | `python -m pytest -q` | **162 passed, 0 failed, 0 skipped**, 541 warning | 252.16 s (4:12) | ✅ воспроизводимо |
| Изолированный поднабор (3 модуля) | `pytest -q tests/test_topology_api.py tests/test_sync_api.py tests/test_ux_api.py` | 25 passed | 34.11 s | ✅ нет зависимости от полного прогона |
| Фронтенд typecheck | `npm run typecheck` (`tsc -b --noEmit`) | ошибок нет, код 0 | 5.5 s | ✅ |
| Фронтенд typecheck, полный (без incremental) | `node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json` | ошибок нет, код 0 | 5.0 s | ✅ не «пустышка» из-за tsbuildinfo |
| Фронтенд build | `npm run build` (`tsc -b && vite build`) | успешно, 508 модулей, 1 warning о размере чанков | 12.3 s (vite: 6.03 s) | ✅ |
| Фронтенд unit-тесты (сверх задачи, бонус) | `npm run test` (`vitest run`) | 2 файла / 6 тестов passed | 1.42 s | ✅ |
| Идентичность БД под тестами | read-only `select current_database()` | `karier_test_db` (PostgreSQL 18.3) | — | ✅ рабочая БД не затронута |

Итог базлайна: **бэкенд и фронтенд «зелёные», флейков и падений нет**. Основные проблемы — не в
результате прогонов, а в инфраструктуре качества: нет метрик покрытия, нет CI, нет конфига pytest,
нет тестов на миграции, очень слабое покрытие фронтенда (2 unit-файла на ~13 тыс. строк) и
29 API-маршрутов без явных тестов.

## Окружение

| Компонент | Значение |
|---|---|
| ОС | Windows 10 Pro 10.0.19045, локальная TZ UTC+08:00 |
| Python (backend-v2 venv) | 3.14.10 |
| pytest | 8.3.4 |
| FastAPI / Starlette / Pydantic / SQLAlchemy | 0.115.0 / 0.38.6 / 2.14.4 / 2.0.36 |
| PostgreSQL | 18.3 (x86_64-windows), порт 5432 |
| Node.js / npm | v26.13.1 / 11.20.0 |
| TypeScript / Vite / Vitest / React | 5.9.3 / 5.4.21 / 2.1.8 / 18.3.1 |
| Тестовая БД | `karier_test_db` (31 таблица в схемах gis/auth/ops/audit/sync/public, `gis.assets` = 5292 строки) |

## 1. Изоляция тестовой БД (шаг 1 задачи)

Переменная `DATABASE_URL` в окружении **не была задана** — снимать было нечего; для надёжности
перед каждым прогоном выполнялось:

```powershell
$env:DATABASE_URL = $null; Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Write-Output "DATABASE_URL after unset: [$env:DATABASE_URL]"   # -> []
Write-Output "TEST_DATABASE_URL: [$env:TEST_DATABASE_URL]"     # -> []
```

`TEST_DATABASE_URL` тоже не задана, поэтому `tests/conftest.py` берёт дефолт
`postgresql+psycopg://karier_user:***@127.0.0.1:5432/karier_test_db`.
Защита от случайного запуска на рабочей БД в conftest двухуровневая и проверена чтением кода:

* если `DATABASE_URL` задан и его база ≠ `karier_test_db` → `RuntimeError` **до** первого теста;
* после импорта `app` проверяется, что `settings.DATABASE_URL` реально смотрит в `karier_test_db`.

Фактическая база под тестами подтверждена отдельным read-only запросом (после прогонов):

```
current_database = karier_test_db
server = PostgreSQL 18.3 on x86_64-windows
tables = 31
gis.assets rows = 5292
```

Сброс тестовой БД (`C:\karier\test-db-reset.cmd`) **не потребовался** — оба полных прогона прошли
на уже существующей БД, состояние переиспользовалось.

## 2. Бэкенд: pytest

Рабочая директория `C:\karier\karier\backend-v2`, интерпретатор — venv проекта.

```powershell
$env:DATABASE_URL = $null
.\venv\Scripts\python.exe -m pytest -q
```

### Прогон 1 — хвост вывода

```
........................................................................ [ 44%]
........................................................................ [ 88%]
..................                                                       [100%]
============================== warnings summary ===============================
...
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
162 passed, 541 warnings in 230.84s (0:03:50)
EXITCODE=0
DURATION=234,4s
```

### Прогон 2 (контрольный, тот же код и та же БД) — хвост вывода

```
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
162 passed, 541 warnings in 252.16s (0:04:12)
RUN2_EXIT=0
RUN2_DURATION=255,6s
```

* passed/failed/skipped: **162 / 0 / 0** в обоих прогонах (тестов-функций в 26 файлах — 162,
  параметризации нет, поэтому число совпадает);
* длительность: 230.8 s и 252.2 s (разброс ~9 %, объясним прогревом кэшей/нагрузкой машины);
* предупреждений: 541 в каждом прогоне, состав идентичен;
* падений нет → списка упавших тестов нет.

### Предупреждения (все — из сторонних библиотек, ни одного из кода проекта)

| Источник | Кол-во | Текст |
|---|---|---|
| `starlette/testclient.py:40` | 1 | `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated…` |
| `fastapi/routing.py:233` | 235 | `DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16` |
| `starlette/_utils.py:40` | 239 | то же `asyncio.iscoroutinefunction` |
| (распределение по тест-модулям) | 66 | тот же `starlette/_utils.py:40`, по одному на тест, который поднимает TestClient |
| **Итого** | **541** | |

Практический смысл: стек FastAPI 0.115 / Starlette 0.38 на Python 3.14 живёт на устаревших API,
которые **удаляются в Python 3.16**. Это не ошибка сейчас, но это жёсткий дедлайн на обновление
зависимостей до перехода на 3.16 (а также повод зафиксировать версию Python в CI).

### Состав набора (162 теста / 26 файлов)

| Файл | Тестов | Файл | Тестов |
|---|---|---|---|
| test_admin_api.py | 11 | test_sketch_v3.py | 7 |
| test_gis_api.py | 11 | test_sketch_v4.py | 7 |
| test_topology_api.py | 9 | test_sketch_v5.py | 6 |
| test_sync_api.py | 9 | test_sketch_v6.py | 7 |
| test_mcp_tools.py | 9 | test_sketch_v2.py | 4 |
| test_auth_api.py | 9 | test_blocks_s18.py | 6 |
| test_ux_api.py | 7 | test_blocks_s20.py | 1 |
| test_schema_blocks.py | 7 | test_blocks_s21.py | 3 |
| test_gost_schema.py | 7 | test_line_builder.py | 4 |
| test_schema_builder.py | 6 | test_ops_api.py | 6 |
| test_schema_snapshots.py | 5 | test_reports_api.py | 6 |
| test_break_glass.py | 5 | test_sprint12_api.py | 4 |
| test_final_api.py | 3 | test_undo_restore.py | 3 |

## 3. Фронтенд: typecheck и build

Рабочая директория `C:\karier\karier\src-v2`.

### typecheck

```powershell
npm.cmd run typecheck     # -> tsc -b --noEmit
```

```
> karier-web-v2@0.1.0 typecheck
> tsc -b --noEmit
TYPECHECK_EXIT=0
TYPECHECK_DURATION=5,5s
```

Важная деталь: `tsc -b` в проектном режиме опирается на `tsconfig.tsbuildinfo`. Чтобы исключить
«зелёный по кэшу» результат, дополнительно выполнен полный неинкрементальный прогон:

```powershell
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json
```

```
FULL_TYPECHECK_EXIT=0
FULL_TYPECHECK_DURATION=5,0s
```

Вывод: типы чистые по всему `include: ["src"]` (55 файлов `.ts/.tsx`, ~12 950 строк; `strict: true`,
`noUnusedLocals`, `noUnusedParameters` включены).

### build

```powershell
npm.cmd run build         # -> tsc -b && vite build
```

```
vite v5.4.21 building for production...
transforming...
✓ 508 modules transformed.
computing gzip size...
dist/index.html                        1.06 kB │ gzip:   0.57 kB
dist/assets/SchemaView-B2Kz5wtG.css   15.10 kB │ gzip:   2.56 kB
dist/assets/index-QiirDn1i.css        53.37 kB │ gzip:  13.95 kB
dist/assets/SchemaView-BBpK8O55.js   334.64 kB │ gzip: 109.07 kB │ map: 1,428.50 kB
dist/assets/QrScanner-D_3EUQgK.js    335.99 kB │ gzip: 100.83 kB │ map: 1,739.82 kB
dist/assets/index-CACf1wFE.js        620.96 kB │ gzip: 192.66 kB │ map: 2,242.24 kB
✓ built in 6.03s

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking
BUILD_EXIT=0
BUILD_DURATION=12,3s
```

Наблюдения по сборке:

* основной чанк `index-*.js` — 621 kB (192.7 kB gzip), предупреждение Vite о лимите 500 kB;
  `QrScanner` и `SchemaView` уже выделены в отдельные чанки, но сами по ~335 kB;
* `vite.config.ts` содержит `build.sourcemap: true`, поэтому в `dist` лежат `.map` на 1.4–2.2 MB
  (в проде это и объём, и потенциальная утечка исходников — вопрос политики, не ошибка сборки);
* артефакты сборки перезаписали `src-v2/dist` и `src-v2/tsconfig.tsbuildinfo` (это результаты
  сборки, исходники и тесты не тронуты).

## 4. Флейки и стабильность

* **Флейков не обнаружено**: два полных последовательных прогона дали побайтно одинаковый итог
  (162 passed, 541 warnings), набор не зависит от остаточных данных предыдущего прогона —
  тестовая БД между прогонами не сбрасывалась.
* **Изоляция модулей**: три наиболее «грязных» по состоянию модуля прогнаны отдельно от всего
  набора — `25 passed, 487 warnings in 34.11s`, то есть эти тесты не полагаются на то, что до них
  «что-то создали» другие файлы.
* **Спящий skip**: в `tests/test_mcp_tools.py:86` есть условный `pytest.skip("в демо-данных не
  осталось свободной пары портов")` — при «забитой» тестовой БД набор молча станет `161 passed,
  1 skipped` вместо падения. Сейчас он не срабатывает, но это тихая деградация, а не сигнал.
  Рекомендуется превратить в явную ошибку или в подбор пары через API.
* **Ограничение метода**: порядок выполнения pytest детерминирован (без `pytest-randomly`
  и плагинов перемешивания), поэтому систематическая зависимость от порядка может быть не видна.
  Проверка `-p randomly` (случайный порядок) в базлайн не входит и не выполнялась.

### Риски тестовой инфраструктуры (в порядке важности)

1. **Нет изоляции транзакцией.** `conftest.py` использует session-scoped `TestClient` и общую БД;
   `autouse`-фикстура `heal_topology` возвращает в эталон только 6 объектов (`BKRU1-*`, `KTP-14`)
   и связи. Всё остальное, что создают тесты (сотрудники, типы, дефекты, документы, слои карты),
   **остаётся в `karier_test_db`** после прогона.
2. **Зависимость от seed-данных.** Набор требует заранее засеянной демо-БД (`seed.py`, сотрудники
   `000001`/`000002`, TOTP-секрет оператора, ≥20 объектов, ≥10 связей). Пустая тестовая БД = падение
   почти всего набора, а не понятная ошибка «прогоните seed».
3. **Нет конфига pytest.** Ни `pytest.ini`, ни `pyproject.toml`, ни `setup.cfg` в `backend-v2`:
   нет `addopts`, маркеров, `--strict-markers`, `--strict-config`, нет фильтров предупреждений,
   нет таймаутов и `--durations`. Набор не воспроизводится «одной командой с политикой».
4. **Нет CI.** Каталога `.github/workflows` (и любых других CI-конфигов) в репозитории нет —
   ни один из шагов этого базлайна не выполняется автоматически, регрессии ловятся только вручную.

## 5. Пробелы покрытия

### 5.1. Бэкенд-маршруты без явных тестов

Метод: из роутеров извлечены все 117 маршрутов (`/api` + префиксы), затем проверено, встречается ли
путь (с нормализацией `{param}`) в тексте тестов. 88 маршрутов упоминаются, **29 — нет**. Это
текстовая эвристика (может и завышать, и занижать), но выборочная проверка подтвердила перечисленное:

| Группа | Маршруты | Комментарий |
|---|---|---|
| Аутентификация | `POST /api/auth/refresh`, `POST /api/auth/logout` | refresh-cookie и инвалидация сессии **не тестируются** — критичный для безопасности путь |
| Профиль (`me.py`) | `POST /api/me/password`, `GET /api/me/sessions`, `DELETE /api/me/sessions/{id}`, `POST /api/me/mfa/totp/enroll|confirm|disable` | тестируется только `GET /api/me`; самостоятельная выдача 2FA и смена пароля — нет |
| Здоровье | `GET /api/health/live` | тестируется только `/api/health/ready` |
| Сотрудники | `POST /api/employees/{id}/unblock`, `/reset-password`, `/resend-invite` | блокировка покрыта, обратные операции — нет |
| Линии | `GET /api/lines`, `POST /api/lines` | линейные объекты не тестируются как API (только построитель схем) |
| Связи | `POST /api/links/{link_id}/state` | переключение состояния связи — нет |
| Схема/топология | `GET /api/topology/switching` | — |
| Группы объектов | `POST /api/asset-groups`, `POST /api/asset-groups/{asset_id}/ungroup` | — |
| Обслуживание | `GET|POST /api/assets/{asset_id}/maintenance`, `DELETE /api/maintenance/{id}` | сервис `maintenance.py` не покрыт через API |
| Порты | `POST /api/assets/{asset_id}/ports/ensure` | — |
| Опоры ВЛ | `POST /api/schema/poles/generate`, `/renumber`, `/renumber-chain` | `services/poles.py` не покрыт |
| Композиты | `POST /api/composites/place`, `POST /api/composites/{parent_id}/attach` | `services/composite.py` не покрыт |
| Медиа | `GET /api/media/{media_id}/file`, `DELETE /api/media/{media_id}` | загрузка/список медиа покрыты, скачивание и удаление — нет |

### 5.2. Прочие пробелы бэкенда

* **Метрик покрытия нет.** `pytest-cov` не установлен, запуск с `--cov` не настроен → процент
  покрытия строк сейчас **неизвестен**; «162 passed» не равно «покрыто».
* **Миграции не тестируются.** 14 версий Alembic, но ни одного теста на `alembic upgrade head`
  с нуля, на downgrade и на расхождение «модели ↔ миграции» (схема-дрейф). Риск: свежий стенд
  поднимается по миграциям, а тесты гоняются на уже засеянной БД.
* **Rate limiting не тестируется.** `app/core/rate_limit.py` есть, тестов на 429/лимиты нет.
* **Таймауты/нагрузка/конкурентность.** Есть точечные тесты гонок синхронизации
  (`test_sync_api.test_move_race_keeps_both_moves`), но нет тестов на параллельные записи,
  идемпотентность под нагрузкой, деградацию при недоступной БД.
* **`services/*` покрыты только косвенно** через API; модули без API-тестов (`poles.py`,
  `composite.py`, `maintenance.py`, `notify.py`, `analytics.py`) не покрыты и напрямую.
* **Легаси-код вне тестов.** Каталоги `backend/` (v1) и `src/` (v1, 29 файлов) не имеют тестов
  вообще. Пока они лежат в репозитории, они выглядят как «непроверенная часть продукта» —
  нужна явная пометка «архив/не используется» либо удаление (это вопрос к аудиту, не к QA).

### 5.3. Фронтенд

* Unit-тестов: **2 файла на ~13 тыс. строк** — `src/lib/dxf.test.ts`, `src/lib/photo.test.ts`
  (6 тестов, 1.42 s). Покрыты только две утилиты (`lib/`), компоненты и страницы — нет.
* Нет компонентных тестов (React Testing Library) и нет E2E (Playwright/Cypress): сквозные
  сценарии (вход, реестр, схема, инспекции, офлайн-синхронизация) **не проверяются автоматически**.
* Нет скрипта `coverage` для vitest (`@vitest/coverage-v8` не установлен) → процент покрытия
  фронтенда неизвестен.
* Покрытия типов недостаточно как гарантии: `tsc` зелёный (это хорошо), но `strict` не заменяет
  поведенческих тестов; `any`/приведения типов в коде отдельно не измерялись (это тема аудита
  фронтенда, см. `02-frontend-audit.md`).

## 6. Рекомендации по итогам базлайна (приоритет сверху вниз)

1. **Зафиксировать базлайн в CI** (P0): job «backend pytest на karier_test_db» + job
   «typecheck & build» + «vitest». Сейчас всё это ручное; любой регресс доедет до пользователя.
2. **Добавить замер покрытия** (P1): `pytest-cov` (`--cov=app --cov-report=term-missing`) и
   `@vitest/coverage-v8`; зафиксировать стартовые цифры и не опускать их.
3. **Изоляция тестов** (P1): транзакция-на-тест (rollback) либо гарантированный сброс
   `karier_test_db` перед прогоном; сейчас тесты оставляют данные в БД и зависят от seed.
4. **Тесты на миграции** (P1): прогон `alembic upgrade head` на пустой БД в CI + сравнение
   метаданных моделей со схемой (autogenerate-diff должен быть пустым).
5. **Закрыть дыры в безопасности** (P1): тесты на `auth/refresh`, `auth/logout`, смену пароля,
   сессии и самостоятельное подключение/снятие TOTP; rate limiting (429).
6. **Конфиг pytest** (P2): `pyproject.toml` c `addopts = -q --strict-markers --strict-config`,
   `filterwarnings`, `--durations=10`, маркеры `slow`/`integration`; убрать «спящий» skip в
   `test_mcp_tools.py:86`.
7. **Тесты на непокрытые API-группы** (P2): обслуживание, опоры ВЛ, композиты, группы объектов,
   линии, скачивание/удаление медиа, `ports/ensure`, `topology/switching`.
8. **Фронтенд-тесты** (P2): минимум smoke-тесты ключевых страниц (RTL) и один E2E-сценарий
   «вход → реестр → схема»; сейчас фронтенд держится только на `tsc` и ручной проверке.
9. **Обновить Python-стек до 3.16** (P2): 541 deprecation-warning — это обратный отсчёт;
   обновление FastAPI/Starlette лучше сделать плановым, а не аварийным.
10. **Сборка** (P3): разбить основной чанк 621 kB (`manualChunks`/`dynamic import`), решить
    судьбу `sourcemap: true` в проде.

## 7. Границы проверки (что НЕ проверялось)

* Рабочая БД `karier_db` и рабочий стек (порты 8001/5174 и сервисы) не затрагивались; стек не
  перезапускался. Единственное обращение к БД вне тестов — read-only `select current_database()`
  к `karier_test_db`.
* Тестовая БД не сбрасывалась (`C:\karier\test-db-reset.cmd` не вызывался) — в отчёте это
  отражено как факт, а не как рекомендация.
* Не выполнялись: мутационное тестирование, нагрузочное тестирование, проверка безопасности
  (SAST/DAST), e2e-прогон в браузере, случайный порядок тестов (`pytest-randomly`), замер покрытия.
* Код, тесты, конфиги не изменялись. Изменены только артефакты сборки (`src-v2/dist`,
  `src-v2/tsconfig.tsbuildinfo`) — как побочный эффект обязательного шага `npm run build`.

## Приложение: сохранённые логи

Полные логи прогонов (вне репозитория, чтобы не засорять проект):

* `C:\karier\.tmp\qa-baseline\pytest.log` — прогон 1;
* `C:\karier\.tmp\qa-baseline\pytest-run2.log` — прогон 2;
* `C:\karier\.tmp\qa-baseline\typecheck.log` — вывод `tsc -b --noEmit` (полный прогон без
  incremental-режима ошибок не дал, поэтому файла `typecheck-full.log` нет: Tee-Object не создаёт
  файл для пустого потока);
* `C:\karier\.tmp\qa-baseline\build.log`;
* `C:\karier\.tmp\qa-baseline\vitest.log`.
