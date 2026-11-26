# 11 — V1: приёмка волны 1 (S-1, S-1b, S-2)

Дата: 2026-11-25, 07:47–11:45 по локальному времени машины (UTC+08:00).
Исполнитель: `qa-runner` (QA-инженер команды `karier-improvements`).
Предмет: волна 1 — S-1 (гигиена репозитория, t7), S-1b (ротация пароля `karier_user`, t9),
S-2 (пять исправлений последних правок, t8).

## ВЕРДИКТ: **pass** (с оговорками, вынесенными в S-9 / S-10)

Волна 1 не внесла регрессий, проверенных этим гейтом:

* секретов (старого пароля) в отслеживаемом дереве **0**, побайтовый скан вне `.env*` — **0**;
* ротация реальная: старый и случайный пароль **отклоняются**, новый **принимается**;
  рабочее приложение после ротации отвечает и пускает (`health/ready = ok`, вход `000001/admin`,
  `/api/topology/graph = 200`);
* контракт 422 восстановлен: `fields` — машинные ключи, `field_labels` — русские подписи,
  `detail` по-русски, `application/problem+json` сохранён;
* два **полных** прогона pytest, каждый после канонического `test-db-reset.cmd`, — **по 173 passed,
  0 failed**; дерево тестов не менялось между прогонами (SHA256 стабилен);
* `tsc --noEmit` и `vite build` — exit 0;
* git-гигиена в порядке: `venv.broken*` нет ни в статусе, ни в HEAD, `.gitattributes`/`.gitignore`
  на месте.

Оговорки (не провал волны 1, переданы в отдельные задачи):
`test_registration_flow` — data-flake из-за «грязного» демо-дампа (S-9);
повторный прогон без сброса БД накапливает данные и нестабилен (S-9);
`alembic check` не пуст из-за предсуществующего дрейфа моделей/БД (S-10).

## Сводная таблица

| # | Проверка | Результат | Доказательство |
|---|---|---|---|
| 1 | Поиск старого пароля по дереву (без `.local`, `venv*`, `node_modules`, `dist`, `backups`, `.env*`) | **PASS** — 0 совпадений | `git grep` worktree=0, HEAD=0; побайтовый скан 637 файлов / 35 023 289 байт → 0 |
| 2 | `GET /api/health/ready` = ok | **PASS** | `200 {"status":"ok","database":"ok"}` — и на рабочем стеке (8001), и на тестовой БД (8002) |
| 3 | Вход `000001/admin` работает после ротации | **PASS** | `200`, `role=admin`, `access_token` выдан; пароль из `.env`/`.env.test` = новый, старый отклонён БД |
| 4 | `GET /api/topology/graph` = 200 | **PASS** | 8001: `200` (1 узел — рабочая БД в состоянии clean slate); тестовая БД: `200` (109 узлов / 678 связей / 56 блоков после прогона; 126/871/72 сразу после сброса) |
| 5 | Контракт 422: `fields` — машинный ключ `name`, `field_labels` — подпись | **PASS** | `fields={"name":"минимум 2 символа"}`, `field_labels={"name":"Название"}`, `detail="Название: минимум 2 символа"`, `application/problem+json` |
| 6 | pytest полный прогон дважды (162 + новые), 0 failed | **PASS** | Прогон 1: 173 passed, 546 warnings, 477.07 s; прогон 2: 173 passed, 545 warnings, 425.39 s; оба после сброса БД; SHA256 `tests/` одинаков до/после |
| 7 | `tsc --noEmit` и `vite build` — exit 0 | **PASS** | typecheck exit 0 (12.3 s); build exit 0 (23.4 s; vite 11.61 s, 508 модулей) |
| 8 | `alembic autogenerate` пустой, голова одна | **PASS с оговоркой** | голова ровно одна: `0014_schema_snapshots (head)`, `current` = `0014`; дифф **не пуст** — 29 предсуществующих операций, **ни одной по `schema_snapshots`** (цель S-2 достигнута); по решению капитана — baseline, задача S-10 |
| 9 | git status без `venv.broken*`, `.gitattributes`/`.gitignore` на месте | **PASS** | 39 записей (21 M + 18 ??), `venv.broken`/`.pyc`/`venv/` в статусе и в HEAD = 0; оба файла `git ls-files` подтверждает |
| 10 | Отчёт с таблицей проверка/результат/доказательство и вердиктом | **PASS** | этот файл |

## 1. Секреты и гигиена репозитория (S-1)

### 1.1. Поиск старого пароля

```powershell
$git = 'C:\karier\tools\MinGit\cmd\git.exe'; Set-Location C:\karier\karier
& $git grep -n --fixed-strings '<старый_пароль>'        # exit=1 (совпадений нет)
& $git grep -n --fixed-strings '<старый_пароль>' HEAD   # exit=1 (совпадений нет)
& $git grep -n --fixed-strings 'postgresql+psycopg://karier_user:'   # 1 совпадение
```

Единственное совпадение по DSN — заглушка в коде, пароля в ней нет:

```
backend-v2/app/core/config.py:34:  f"postgresql+psycopg://karier_user:{PLACEHOLDER_DB_PASSWORD}@127.0.0.1:5432/karier_db"
```

Дополнительно `git grep -E 'SECRET_KEY\s*=\s*"?dev-'` → 0 совпадений.
Трекаемых `.env` нет: `.gitignore:47` — `.env`, `.gitignore:29` — `backend-v2/tests/.env.test`
(`git ls-files | Select-String '(^|/)\.env'` → только `backend-v2/.env.example`).

### 1.2. Побайтовый скан рабочего дерева

Метод: обход `C:\karier\karier` без каталогов `.git`, `.local`, `venv`, `venv*`, `.venv`,
`node_modules`, `dist`, `backups`, `.npm-cache`, `.tmp`, `__pycache__`, `.pytest_cache`, `.vs`,
`site-packages`, `.vercel`; поиск байтовых последовательностей старого пароля в каждом файле.

```
scanned files: 637  bytes: 35023289
HITS outside .env*: 0
HITS in .env* files: 1   ->  backend\.env
```

Вывод: в коде, тестах, документации и конфигах репозитория старого пароля нет.
`backend\.env` — легаси-файл v1-бэкенда (untracked, в `.gitignore`), в критерий не входит;
замечание вынесено в §7.

### 1.3. Git-гигиена

```powershell
& $git status --porcelain          # 39 записей: 21 M + 18 ??
& $git ls-tree -r --name-only HEAD | Select-String 'venv\.broken|\.pyc$'   # 0
& $git ls-files --error-unmatch .gitattributes .gitignore                  # оба трекаются
& $git log --oneline -3
# bf9fabe chore(git): renormalize line endings
# b88b965 chore(security): убрать пароль БД и dev-секреты из кода, гигиена репозитория
# efd3cd2 feat(types): автокомплектность типов с подтипами
```

`.gitattributes`: `* text=auto eol=lf`, для `*.ps1/*.cmd/*.bat` — `eol=crlf`,
бинарные расширения помечены `binary`. Политика EOL зафиксирована и трекается.

Незакоммиченные 39 записей — осознанно оставленное рабочее состояние владельца (в т.ч. правки
S-2/S-8). Отдельно отмечу: файл миграции `backend-v2/alembic/versions/0014_schema_snapshots.py`
в статусе числится как **untracked** — при подготовке чистого репозитория его нужно добавить в
индекс, иначе схема снимков не воспроизведётся из репозитория.

## 2. Ротация `karier_user` и работоспособность после неё (S-1b)

### 2.1. Реальная проверка пароля включена

`C:\karier\.local\pg18\data\pg_hba.conf` (после S-1b):

```
local   all             all                                     trust
host    all             karier_user    127.0.0.1/32            scram-sha-256
host    all             karier_user    ::1/128                 scram-sha-256
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
```

Строки `scram-sha-256` для роли `karier_user` стоят **перед** общими `trust` — поэтому для неё
пароль проверяется по-настоящему, остальные локальные подключения остались как были.

### 2.2. Пробы подключения (только `connect`, без DDL/DML)

| Пароль | Результат |
|---|---|
| новый (из `backend-v2/tests/.env.test`) | **ACCEPTED**: `(karier_user, karier_test_db)` |
| старый | **REJECTED**: `FATAL: password authentication failed for user "karier_user"` |
| случайный | **REJECTED**: то же |

Это и есть доказательство ротации: до S-1b локальный `trust` пускал с любым паролем
(проверено — «неверный пароль» принимался), после S-1b старый пароль не работает.
Важная деталь для ревью: `pg_hba.conf` вне репозитория, поэтому политика аутентификации
не версионируется — при переносе на другой стенд её нужно воспроизводить отдельно.

### 2.3. Окружение и скрипт сброса обновлены

* `backend-v2/.env`, `backend-v2/tests/.env.test` — обновлены (старого пароля не содержат);
* `C:\karier\.local\reset-test-db.ps1` — старого пароля больше нет; канонический
  `C:\karier\test-db-reset.cmd` **успешно** отработал три раза за гейт (см. §4.1), значит
  после ротации он рабочий.

### 2.4. Приложение после ротации

Рабочий стек (8001, рабочая БД `karier_db`, состояние clean slate):

```
GET  /api/health/ready      -> 200 {"status":"ok","service":"karier-api","database":"ok"}
POST /api/auth/login 000001 -> 200, token выдан, role=admin
GET  /api/topology/graph    -> 200: nodes=1, edges=0, blocks=1   (в рабочей БД один объект PS_35-1)
GET  /api/topology/graph без токена -> 401
```

Изолированный экземпляр на тестовой БД (`karier_test_db`, порт 8002):

```
GET  /api/health/ready      -> 200 {"status":"ok","database":"ok"}
POST /api/auth/login 000001 -> 200, role=admin
GET  /api/topology/graph    -> 200: nodes=126, edges=871, blocks=72 (сразу после сброса)
                               и  200: nodes=109, edges=678, blocks=56 (после двух прогонов)
GET  /api/topology/graph без токена -> 401
```

Числа различаются, потому что тесты меняют тестовую БД; для приёмки важно, что эндпоинт
отвечает 200 и структура графа корректна.

## 3. Контракт 422 (`fields` + `field_labels`)

```http
POST /api/assets
{"name": "", "type_code": "ktp"}
```

```
HTTP 422, content-type: application/problem+json
{
  "type": "https://karier.local/errors/validation.failed",
  "title": "Название: минимум 2 символа",
  "status": 422,
  "code": "validation.failed",
  "detail": "Название: минимум 2 символа",
  "instance": "/api/assets",
  "request_id": "8fe9fc35-...",
  "fields": {"name": "минимум 2 символа"},
  "field_labels": {"name": "Название"}
}
```

Второй случай (две ошибки сразу):

```http
POST /api/assets  {"name": "Объект контракта", "x": "не число"}
```

```
HTTP 422
fields:       {"type_code": "обязательное поле", "x": "ожидается число"}
field_labels: {"type_code": "Тип", "x": "X"}
detail:       "Тип: обязательное поле (и ещё 1)"
```

Итог: машинные ключи (`name`, `type_code`, `x`) вернулись в `fields`, русские подписи живут
отдельно в `field_labels`, `detail` остаётся человекочитаемым, «и ещё N» работает.
Проверено и на рабочей БД (8001), и на тестовой (8002) — поведение одинаковое.
Тесты `tests/test_api_contract_validation.py` (3 шт.) закрепляют именно этот контракт.

## 4. Полные прогоны pytest (дважды, по канону сброса БД)

### 4.1. Порядок и тайминги

Каждый прогон выполнялся **после** `C:\karier\test-db-reset.cmd` (пересобирает только
`karier_test_db`), параллельных pytest не было (проверялось перед стартом).

| Этап | Длительность | Итог |
|---|---|---|
| RESET#1 | 357.8 s | `karier_test_db` пересобрана: assets 4700, links 3788, blocks 17, employees 87, types 18, alembic `0014_schema_snapshots` |
| PYTEST#1 | 477.07 s (wall 485.1 s) | **173 passed**, 546 warnings, exit 0 |
| RESET#2 | 435.3 s | то же состояние БД |
| PYTEST#2 | 425.39 s (wall 433.7 s) | **173 passed**, 545 warnings, exit 0 |

Состав набора: 173 = 162 базовых + 3 (`test_api_contract_validation.py`, S-2)
+ 2 (`test_schema_snapshots.py`, S-2) + 1 (`test_schema_builder.py`, S-2)
+ 5 (`test_topology_api.py`, фидеры S-8).

Предупреждения (546/545) — те же сторонние deprecation-предупреждения FastAPI/Starlette на
Python 3.14, что зафиксированы в базлайне (`docs/team/03-qa-baseline.md`); разница в один
warning между прогонами — накопление/дедупликация предупреждений в рамках сессии, на результат
не влияет.

### 4.2. Дерево не менялось во время прогонов

SHA256 всего каталога `backend-v2/tests/*.py` (29 файлов) снимался 5 раз — до первого прогона,
до/после каждого прогона:

| Снимок | tree_sha256 |
|---|---|
| before-run1 | `bb1fb871ae4d7fe91eaa86d08ef413929284655a09bdea1994071d68a371badb` |
| before-pytest1 | `bb1fb871…71badb` |
| after-pytest1 | `bb1fb871…71badb` |
| before-pytest2 | `bb1fb871…71badb` |
| after-pytest2 | `bb1fb871…71badb` |

Хеши идентичны → тесты во время прогонов не правились, результаты зачётные.
(В логе последовательности остались строки `WARNING: tests/ changed during pytest run` — это
дефект моего скрипта: функция возвращала вместе с хешем служебную строку; `Compare-Object`
между снимками дал пустой список, см. `hash-*.txt` в каталоге логов.)

### 4.3. Повторный прогон **без** сброса БД — нестабилен (вход для S-9)

Промежуточная попытка (до стабилизации дерева) шла подряд, без сброса:

* первый такой прогон на уже «использованной» БД дал `167 passed, 1 failed`
  (`test_registration_flow`, см. §4.4) — набор из 168 тестов, дерево тогда ещё правилось (S-8);
* после прогона накопление данных измеримо: было `assets 4700 / links 3788 / employees 87`,
  стало `assets 4979 (active 812) / links 3987 / employees 89 / defects 147`.

То есть один полный прогон оставляет в `karier_test_db` сотни объектов; при серии прогонов
активных объектов становится больше 1000, и хелперы тестов с `limit=1000` начинают вести себя
нестабильно (у капитана зафиксировано `StopIteration` в `test_ux_api` при 1721 активном объекте).
Поэтому канон приёмки — «сброс → прогон»; изоляция тестов (уборка за собой) — задача S-9 (t26).

### 4.4. `test_registration_flow` — data-flake демо-дампа (S-9)

Единственное наблюдённое падение: `tests/test_auth_api.py::test_registration_flow`,
`assert 409 == 201` на `POST /api/employees`. Это не регрессия волны 1, а следствие данных:

* тест генерирует случайный табельный `8XXXXX` (`uuid4().int % 100000`) и заводит сотрудника;
* в демо-дампе `backups/karier_before_clean_20261109.dump`, из которого собирается тестовая БД,
  уже лежат **41** сотрудник «Регистров Регистр Регистрович» с табельными `8XXXXX`
  (`created_at` = 2026-11-09) — следы прежних прогонов, попавшие в дамп;
* `POST /api/employees` при совпадении табельного отдаёт 409 `employee.duplicate_tab`
  (`app/api/routers/employees.py:108-109`) — тест на это не рассчитан.

Статистика: 10 повторов теста на свежей БД — **10 passed, 0 failed**; заполненность диапазона
`8XXXXX` в БД — 42–52 значения из 100000, т.е. вероятность коллизии ≈ 0.05 % за прогон.
После сброса вероятность снова 41/100000, но каждый успешный прогон добавляет ещё один
табельный, поэтому со временем частота растёт.

Требование в S-9: сделать тест детерминированным (уникальный префикс/проверка занятости
табельного до создания/уборка за собой) и почистить демо-дамп от «Регистровых» сотрудников.

## 5. Фронтенд: typecheck и build

Рабочая директория `C:\karier\karier\src-v2`, финальное дерево (frontend-исходники не менялись
с 24.11):

```powershell
npm.cmd run typecheck   # tsc -b --noEmit
npm.cmd run build       # tsc -b && vite build
```

```
TYPECHECK_EXIT=0  dur=12.3s
BUILD_EXIT=0      dur=23.4s
vite v5.4.21 building for production...
✓ 508 modules transformed.
dist/index.html                        1.06 kB │ gzip:   0.57 kB
dist/assets/SchemaView-B2Kz5wtG.css   15.10 kB │ gzip:   2.56 kB
dist/assets/index-QiirDn1i.css        53.37 kB │ gzip:  13.95 kB
dist/assets/SchemaView-BBpK8O55.js   334.64 kB │ gzip: 109.07 kB │ map: 1,428.50 kB
dist/assets/QrScanner-D_3EUQgK.js    335.99 kB │ gzip: 100.83 kB │ map: 1,739.82 kB
dist/assets/index-CACf1wFE.js        620.96 kB │ gzip: 192.66 kB │ map: 2,242.24 kB
✓ built in 11.61s
(!) Some chunks are larger than 500 kB after minification.
```

Предупреждение о размере основного чанка (620.96 kB) — известно с базлайна, не регрессия;
`sourcemap: true` по-прежнему кладёт `.map` на 1.4–2.2 MB в `dist` (вопрос S-7).

## 6. Alembic: голова и autogenerate

```powershell
.\venv\Scripts\python.exe -m alembic heads     # 0014_schema_snapshots (head)  — ровно одна голова
.\venv\Scripts\python.exe -m alembic current   # 0014_schema_snapshots (head)  — на тестовой БД
.\venv\Scripts\python.exe -m alembic check     # FAILED: New upgrade operations detected (exit -1)
```

Дифф `alembic check` — 29 операций, и **ни одной по `schema_snapshots`** (именно это требовалось
от S-2: индекс `ix_schema_snapshots_created` и `comment` таблицы объявлены в модели):

| Тип | Объекты | Кол-во |
|---|---|---|
| `remove_index` | `ix_asset_types_parent`, `ix_assets_schema_block`, `ix_defects_active`, `ix_maintenance_at` (есть в БД, не объявлены в моделях) | 4 |
| `add_fk` | `gis.assets.schema_block_id → gis.assets.id`, `ops.defects.deleted_by → auth.employees.id` (есть в моделях, нет в БД) | 2 |
| `remove_table_comment` | комментарии ~23 таблиц (заданы миграциями, не объявлены в моделях) | 23 |

Это предсуществующий дрейф, зафиксированный ранее в `docs/team/09-s2-fixes.md` §8.1; по решению
капитана он трактуется как **baseline**, а не как провал волны 1. Полностью пустой
`alembic check` требует отдельной миграции + правки чужих моделей — задача S-10.

Замечание: `alembic check`/`current` выполнялись на тестовой БД (`DATABASE_URL` из
`tests/.env.test`), рабочая `karier_db` для этого не использовалась.

## 7. Оговорки, известные проблемы и что передано дальше

1. **`test_registration_flow` (data-flake).** Причина — грязный демо-дамп (41 «Регистров»),
   не волна 1. Передано в **S-9 (t26)**: детерминированный тест + чистка дампа.
2. **Повторный прогон без сброса БД нестабилен.** Один прогон оставляет ~+279 assets,
   +199 links, +147 defects; при накоплении >1000 активных объектов хелперы с `limit=1000`
   ломаются. Канон приёмки — «reset → pytest». Изоляция — **S-9 (t26)**.
3. **`alembic check` не пуст.** Предсуществующий дрейф моделей/БД (4 индекса, 2 FK,
   ~23 комментария таблиц), не связан со снимками. **S-10**.
4. **Легаси `backend\.env`** (v1, untracked) всё ещё содержит старый пароль. После ротации он
   недействителен; файл стоит удалить вместе с легаси-каталогом `backend/`. В критерий скана
   не входит (`.env*` вне области), поэтому на вердикт не влияет.
5. **`pg_hba.conf` не в репозитории.** После S-1b для `karier_user` включён `scram-sha-256`,
   но политика аутентификации живёт вне git — при развёртывании на другом стенде её нужно
   воспроизводить (кандидат в F-1/F-2: Docker/compose и инструкция развёртывания).
6. **Миграция `0014_schema_snapshots.py` не в индексе git** (untracked). Перед формированием
   чистого репозитория её нужно добавить, иначе схема снимков не восстановится из кода.
7. **Предупреждения pytest (546/545)** — сторонние deprecation-предупреждения FastAPI/Starlette,
   удаление API в Python 3.16; не связаны с волной 1, требуют планового обновления стека.

## 8. Границы проверки

* Рабочая БД `karier_db` не изменялась по существу: только штатные чтения (`health/ready`,
  `/api/topology/graph`, `/api/assets`), один вход `000001` (создаёт сессию и запись аудита —
  обычная операция приложения) и заведомо невалидный `POST /api/assets`, отклоняемый валидацией
  до обращения к БД. Никаких записей в доменные таблицы `karier_db` не создано.
* Тестовая БД `karier_test_db` пересобиралась только каноническим `C:\karier\test-db-reset.cmd`.
* Рабочий стек не перезапускался; временный экземпляр API поднимался на свободном порту 8002
  поверх `karier_test_db` и после проверок остановлен.
* Код, тесты, конфиги не редактировались: изменены только артефакты сборки `src-v2/dist`
  и `src-v2/tsconfig.tsbuildinfo` (следствие обязательного `npm run build`) и создан этот отчёт.
* Не выполнялись: нагрузочное и мутационное тестирование, E2E в браузере, замер покрытия,
  случайный порядок тестов.

## Приложение: артефакты и версии

Логи и снимки (вне репозитория): `C:\karier\.tmp\qa-v1\`

| Файл | Что внутри |
|---|---|
| `v1-sequence.log` | тайминги reset/pytest, хеши дерева тестов |
| `hash-*.txt` | SHA256 всех `tests/*.py` (5 снимков) |
| `pytest-v1-run1.log`, `pytest-v1-run2.log` | полные выводы финальных прогонов |
| `reset-1.log`, `reset-2.log` | вывод `test-db-reset.cmd` |
| `alembic-check.log` | полный дифф `alembic check` |
| `typecheck-final.log`, `build-final.log` | финальные сборки фронтенда |
| `api-checks-working-8001.json`, `api-checks-test-db.json` | результаты API-проверок |
| `flake-registration-10x.log` | 10 повторов `test_registration_flow` |

Окружение: Windows 10 Pro 10.0.19045; Python 3.14.10; pytest 8.3.4; FastAPI 0.115.0;
Starlette 0.38.6; SQLAlchemy 2.0.36; PostgreSQL 18.3; Alembic 1.14.0; Node.js 26.13.1;
TypeScript 5.9.3; Vite 5.4.21; git 2.47.1 (MinGit, `C:\karier\tools\MinGit\cmd`).
