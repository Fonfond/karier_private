# 11c — V1c: привязка приёмки волны 1 к текущим байтам (после S-4/S-9)

Дата: 2026-11-25, 23:09–23:22 (локальное время машины, UTC+08:00).
Исполнитель: `qa-runner` (`karier-improvements`).
Предмет: перепривязка вердикта волны 1 (S-1, S-1b, S-2) к текущим байтам рабочего дерева после
S-4 (`app/core/config.py`, `app/core/rate_limit.py`, `app/services/sync.py` + тесты) и S-9
(изоляция тестов), потому что снимок V1b (`docs/team/11b-v1-reacceptance.md`) описывал
предыдущую ревизию — находка R1b-1.

## ВЕРДИКТ: **pass**

* Хеши `backend-v2/app/**` и `backend-v2/tests/**` сняты **трижды** (два замера до прогона с
  интервалом ~2 мин и один после) — совпадают, пофайловое сравнение дало **0 изменённых файлов**;
  вердикт привязан к текущим байтам.
* `test-db-reset.cmd` (exit 0, 302.5 с) → полный `pytest -q`: **188 passed, 0 failed, 3 skipped**,
  exit **0** (283.75 с).
* После прогона БД **не разрослась**: `assets_active 585`, `links_active 3737`, `employees 87`,
  тестовых сотрудников `TST-*` — 0, то есть изоляция S-9 работает.
* `POST /api/assets` с пустым `name` → **422** с `fields` и `field_labels`; `health/ready = ok`;
  вход `000001/admin` = 200; `/api/topology/graph` = 200.
* **V1c заменяет снимок V1b** (и, следовательно, V1): вердикт волны 1 действует для
  `app/ 5c508ec5…`, `tests/ f1f67baf…`.

## 1. Хеши: до и после прогона, и чем они отличаются от V1b

Сводный хеш = SHA256 по отсортированному списку строк «sha256 файла + относительный путь».

| Объект | V1b (снимок 25.11 ~20:25) | **V1c (текущий)** | Изменение |
|---|---|---|---|
| `backend-v2/app/**` | `12a39bb2…cb4c` (74 файла) | **`5c508ec591bbcbb81295dd9e9dc04aaf6eca59344097b07735740badf50b0943`** (74 файла) | изменилось содержимое (S-4: `core/config.py`, `core/rate_limit.py`, `services/sync.py`) |
| `backend-v2/tests/**` | `b3815f42…d027` (30 файлов) | **`f1f67baf22c58337925d5ee7657ca4e8317d52dfcff5397585a940010e4faa6a`** (31 файл) | +`tests/test_security_ip.py` (S-4) и правки S-4/S-9 в 5 файлах |
| `backend-v2/app/services/gis.py` | `A0F1E574…4C06` | `A0F1E574E81832390BD4095926E03BF7BE8A64BAF37AF20F70C702BD874F4C06` | **не менялся** (S-4 его не трогал) |
| `.gitignore` | `D78E761B…48E8` | `D78E761BDF40403518FF6C5B22B03086E6463522C74EE2A5349DAAD081A648E8` | не менялся (правки S-3b/гигиена — не волна 1) |
| `backend-v2/requirements.txt` | `730C6F0A…66A8` | `730C6F0A57D2788BB649E82DAD74E1FF5D20AF79A002D58C77C3D3FB600566A8` | не менялся (S-3b, гигиена) |

Замеры (все три — одинаковые по `app/`, `tests/`, `.gitignore`, `requirements.txt`):

| Замер | Время | `app/` | `tests/` |
|---|---|---|---|
| M1 | 23:09:22 | `5c508ec5…0943` | `f1f67baf…aa6a` |
| M2 (через ~2 мин) | 23:11:27 | `5c508ec5…0943` | `f1f67baf…aa6a` |
| M3 (после прогона) | 23:21:18 | `5c508ec5…0943` | `f1f67baf…aa6a` |

Пофайловое сравнение (`Compare-Object` по спискам «хеш + путь»): `app_files=0`, `tests_files=0`.
Условия: окно эксклюзивное (капитан заморозил S-5/R2b), правки S-4 закрыты и закоммиченного
stash-остатка нет, параллельных pytest не было.

`git status --porcelain` на момент старта: **47 записей** (рабочее состояние владельца и
незакоммиченные правки прошлых задач; в хеширование входят только `app/**` и `tests/**`).

## 2. Сброс тестовой БД и полный прогон

```powershell
cmd.exe /c "echo.|C:\karier\test-db-reset.cmd"
cd C:\karier\karier\backend-v2
.\venv\Scripts\python.exe -m pytest -q
```

| Шаг | Длительность | Итог |
|---|---|---|
| `test-db-reset.cmd` (прогон A) | 302.5 с | exit 0; `karier_test_db` пересобрана (assets 4700, links 3788, blocks 17, employees 87, types 18, alembic `0014_schema_snapshots`) |
| `pytest -q` (прогон A) | **283.75 с** | **188 passed, 0 failed, 3 skipped**, 565 warnings, exit **0** |
| `test-db-reset.cmd` (прогон B, контрольный) | 294.1 с | exit 0, то же состояние БД |
| `pytest -q` (прогон B, контрольный) | **281.84 с** | **188 passed, 0 failed, 3 skipped**, 565 warnings, exit **0** |

Прогон B выполнен той же командой из контракта повторно — для воспроизводимости результата:
оба прогона дали одинаковые 188 passed / 3 skipped, хеши и состояние БД после B те же (см. §3).

Собрано 191 тест: 188 passed + 3 skipped. Против V1b (176 тестов) набор вырос на 15: S-4 добавил
8 тестов в `tests/test_sync_api.py` и новый `tests/test_security_ip.py` (8 тестов), S-9 правил
`tests/test_auth_api.py`/`conftest.py`. Поэтому ожидаемое число — 188, а не 173; отличие
зафиксировано здесь как факт (S-8 добавил 5 тестов ещё до V1b).
3 skipped — это `tests/test_migrations.py` (S-3) без `TEST_MIGRATION_DATABASE_URL`, с явной
причиной в тексте пропуска.

## 3. Изоляция S-9: БД после прогона не разрослась

Замеры сделаны прямыми read-only запросами к `karier_test_db` до и после pytest:

| Показатель | До прогона (сразу после reset) | После прогона | Дельта |
|---|---|---|---|
| `gis.assets` активных / всего | 585 / 4700 | 585 / 4700 | 0 / 0 |
| `gis.links` активных | 3737 | 3737 | 0 |
| `auth.employees` | 87 | 87 | 0 |
| из них `TST-*` (тестовая регистрация S-9) | 0 | 0 | 0 |
| из них демо-`8XXXXX` | 41 | 41 | 0 |
| `public.alembic_version` | `0014_schema_snapshots` | `0014_schema_snapshots` | — |

Вывод: autouse-фикстура `isolate_created_rows` (S-9) действительно убирает за собой — повторный
прогон без сброса больше не раздувает базу и не упирается в `limit=1000` (прежняя причина
каскадных падений, зафиксированная в S-8/V1b). После контрольного прогона B (после ещё одного
сброса) состояние БД ровно то же: `assets_active=585`, `total=4700`, `links_active=3737`,
`employees=87`, `TST-*=0`.

## 4. Контракт 422, health/ready, вход, граф

Проверки API — на изолированном экземпляре (порт 8002) поверх `karier_test_db`; рабочая
`karier_db` не затрагивалась (на рабочем стеке 8001 выполнен только read-only `GET /api/health/ready`).

```
GET  /api/health/ready (8002) -> 200 {"status":"ok","service":"karier-api","database":"ok"}
GET  /api/health/ready (8001) -> ready=ok, status=ok (read-only, рабочий стек)
POST /api/auth/login 000001/admin -> 200, access_token выдан, role=admin
GET  /api/topology/graph -> 200 (nodes=92, edges=485, blocks=40)
POST /api/assets {"name":"","type_code":"ktp"}
     -> 422 application/problem+json
        fields       = {"name": "минимум 2 символа"}
        field_labels = {"name": "Название"}
        detail       = "Название: минимум 2 символа"
        code         = validation.failed
POST /api/assets {"name":"Объект контракта","x":"не число"}
     -> 422, fields={"type_code":"обязательное поле","x":"ожидается число"},
        field_labels={"type_code":"Тип","x":"X"}, detail="Тип: обязательное поле (и ещё 1)"
```

## 5. Что заменяет V1c

* `docs/team/11-v1-acceptance.md` (V1) — вердикт pass, но привязан к ревизии с `gis.py 3544f132…`.
* `docs/team/11b-v1-reacceptance.md` (V1b) — вердикт pass для `app/ 12a39bb2…`, `tests/ b3815f42…`.
* **V1c (этот отчёт)** — вердикт pass для `app/ 5c508ec5…`, `tests/ f1f67baf…`; именно эти байты
  содержат закрытые S-4 (RBAC `sync/push`, XFF) и S-9 (изоляция тестов, TTL 720 мин для тестового
  окружения, `faulthandler`-таймаут 180 с).

Для ревью R1b/R2b: ориентироваться на хеши из §1 этого отчёта; снимки V1/V1b считать историческими.

## 6. Наблюдения

| id | severity | Суть |
|---|---|---|
| V1c-1 | info | Набор вырос: 191 тест (188 passed + 3 skipped) против 176 в V1b — за счёт тестов S-4; ожидание «173 passed» из более ранних задач устарело |
| V1c-2 | info | `ACCESS_TOKEN_TTL_MIN=720` в тестовом окружении (conftest, S-9) снимает риск V1b-1 (каскад 401 при замедлении); прогон занял 283.75 с — с большим запасом |
| V1c-3 | info | В `git status` 47 записей незакоммиченных изменений владельца/задач; на привязку вердикта не влияют (хешируются только `app/**` и `tests/**`), но перед push стоит разобрать |

## 7. Границы проверки

* Код, тесты, конфиги не менялись: изменён только этот отчёт.
* Рабочая `karier_db` не затрагивалась: API-проверки — на изолированном экземпляре поверх
  `karier_test_db`, для 8001 — только `GET /api/health/ready`.
* Тестовая БД пересобиралась только каноническим `C:\karier\test-db-reset.cmd`.
* Параллельных pytest не было; после проверок временный API на 8002 остановлен, рабочий стек
  (8001/5174) не перезапускался.
* Не выполнялись: frontend-проверки (вне волны 1; сняты в V1/S-3), нагрузочное тестирование,
  замер покрытия.

## Приложение: артефакты

Каталог `C:\karier\.tmp\qa-v1c\`:

| Файл | Что внутри |
|---|---|
| `v1c-sequence.log` | тайминги, три замера хешей, состояния БД до/после, health рабочего стека |
| `app-m1/m2/m3.txt`, `tests-m1/m2/m3.txt` | пофайловые SHA256 для сравнения |
| `reset.log` | вывод `test-db-reset.cmd` |
| `pytest.log` | полный вывод прогона (188 passed) |
| `api-checks.json` | health/login/422/graph |

Окружение: Windows 10 Pro 10.0.19045; Python 3.14.10; pytest 8.3.4; FastAPI 0.115.0;
Starlette 0.38.6; SQLAlchemy 2.0.36; PostgreSQL 18.3; Alembic 1.14.0; git 2.47.1 (MinGit).
