# 27 — S-9: изоляция тестов (уборка за собой, повторный прогон)

Дата: 2026-11-25, 20:15–… (локальное время машины, UTC+08:00).
Кто: `edit-reviewer`. Задача t26 (implementation), проект `C:\karier\karier`.
Основание: находки V1/V1b (`docs/team/` QA-отчёты) — тесты оставляли данные, повторный
прогон падал на `uq_links_pair_active`, а замедление прогона давало каскад ложных 401.

## Сводка

| # | Проблема | Правка | Файл |
|---|---|---|---|
| A | `Link` вставлен в обход API и не удалялся при падении ассерта → повторный прогон падал на `uq_links_pair_active` | уборка в `try/finally`, delete по id (идемпотентный) | `tests/test_topology_api.py` |
| B | Тесты оставляли объекты/связи/линии/снимки/типы/сотрудников → БД росла (1721→1950 объектов), ложные падения | autouse-фикстура `isolate_created_rows`: снимок PK → удаление только новых строк | `tests/conftest.py` |
| C | `test_registration_flow` генерировал случайный `8XXXXX` (в дампе 41 такой номер) и не убирал сотрудника | детерминированный `TST-<uuid8>` + удаление сотрудника в `finally` | `tests/test_auth_api.py` |
| D | Мёртвый код в `finally` (`for cell in body["items"] if "body" in dir() else []`) и риск `NameError` | `body` инициализируется до `try`, мёртвый цикл убран | `tests/test_line_builder.py` |
| E | V1b-1: 15-минутный access-токен истекал посреди медленного прогона → каскад ложных 401 | TTL для тестов `ACCESS_TOKEN_TTL_MIN=720` + fail-fast проверка | `tests/conftest.py` |
| F | V1b-2: зависший тест блокировал прогон (3000 с) | сторож на тест `TEST_TIMEOUT_SECONDS=180` (faulthandler) | `tests/conftest.py` |

## 1. Уборка связи (A) — `tests/test_topology_api.py`

`test_cycle_detected_in_topology_issues` вставляет `Link` напрямую в БД (в обход API) и
проверяет, что `GET /api/topology/issues` видит обратную связь. Раньше `delete` стоял
**после** `assert`: при падении ассерта строка оставалась живой, и следующий прогон падал
на `uq_links_pair_active` (ровно это случилось на V1).

Теперь проверка и уборка — в одном `try/finally`:

```python
    try:
        issues = client.get("/api/topology/issues", headers=admin_headers).json()
        assert any(issue["code"] == "topology.cycle" for issue in issues)
    finally:
        db = _db()
        try:
            db.execute(text("delete from gis.links where id = :id"), {"id": str(link_id)})
            db.commit()
        finally:
            db.close()
```

Удаление по конкретному id идемпотентно: если строки уже нет — это no-op, исключения не будет.

## 2. Автоочистка (B) — фикстура `isolate_created_rows` (`tests/conftest.py`)

```python
CLEANUP_TABLES = ("gis.links", "gis.assets", "gis.lines",
                  "gis.schema_snapshots", "gis.asset_types", "auth.employees")

@pytest.fixture(autouse=True)
def isolate_created_rows(heal_topology):
    keep = _snapshot_ids()      # снимок PK до теста
    yield
    _delete_new_rows(keep)      # удаляем только «после минус до»
```

Свойства и почему так:

* **снимок PK, а не «удалить всё созданное за сессию»** — seeded-данные и строки
  session-фикстур попадают в снимок и не трогаются; удаляется ровно то, что тест создал сам;
* **зависимость от `heal_topology`** — снимок берётся после штатного «лечения» схемы,
  поэтому поведение `heal_topology` не меняется;
* **порядок удаления** (по требованию контракта):
  `links → assets → lines → schema_snapshots → asset_types → employees`.
  `gis.assets` удаляется после связей и уносит каскадом порты и `schema_blocks`;
  `auth.employees` уносит каскадом `credentials/mfa_factors/sessions/recovery_codes/onboarding_tokens`
  (все они объявлены `ON DELETE CASCADE` в миграции `0001`);
* **идемпотентность и безопасность**: `delete ... where id in :ids` чанками по 500;
  ошибка (например, `RESTRICT` на `gis.asset_types`, если новый тип успел «подхватить»
  seeded-объект) **не валит прогон** — делается `rollback` и `warnings.warn` с таблицей
  и числом пропущенных строк;
* **стоимость**: 6 `select id` до и после каждого теста (сотни–тысячи uuid) — доли
  миллисекунды на запрос, на весь набор порядка секунды; на фоне самих тестов незаметно.

Что это лечит (инвентарь утечек по ast-скану, 38 кандидатов; реальные утечки):
`test_ops_api` (проверки/дефекты/история), `test_sync_api` (перемещения, change_log),
`test_blocks_s18` (свернуть/перемычки), `test_blocks_s21`, `test_sketch_v2`,
`test_admin_api` (дерево типов), `test_schema_snapshots` (снимки), `test_auth_api`
(сотрудник), `test_topology_api` (связи). Негативные тесты (ожидаемые 400/409/422)
ничего не создают — это ложные срабатывания сканера.

## 3. Детерминированный табельный (C) — `tests/test_auth_api.py`

Было: `tab_no = f"8{uuid.uuid4().int % 100000:05d}"` — случайный номер в демо-диапазоне,
где в дампе уже 41 сотрудник (`8XXXXX`) → редкая коллизия давала 409 вместо 201. Плюс
созданный сотрудник не убирался, то есть тест сам увеличивал вероятность коллизии.

Стало:

```python
    tab_no = f"TST-{uuid.uuid4().hex[:8]}"      # вне демо-диапазона + уникальный суффикс
    ...
    finally:
        db = SessionLocal()
        try:
            db.execute(text("delete from auth.employees where tab_no = :tab_no"), {"tab_no": tab_no})
            db.commit()
        finally:
            db.close()
```

`tab_no` — свободная строка 1..16 символов (`schemas/employee.py:16`), поэтому префикс
`TST-` допустим. Удаление безопасно: все FK на `auth.employees` — `SET NULL`, дочерние
auth-таблицы — `CASCADE`.

Важная деталь, найденная на первом прогоне: приложение нормализует табельный
(`strip().upper().replace(" ", "")`, `schemas/employee.py:29`), поэтому суффикс генерируется
в верхнем регистре (`uuid4().hex[:8].upper()`). С нижним регистром тест падал на
`assert done.json()["user"]["tab_no"] == tab_no`, хотя все запросы были 200/201 — регистр
меняло само API.

## 4. Чистка `test_line_builder` (D)

В `test_bulk_cells_numbering_and_sections` в `finally` был мёртвый код
`for cell in body["items"] if "body" in dir() else []: pass`, а сам `body` присваивался
внутри `try`: если POST падал до присваивания, `finally` получал `NameError` и маскировал
исходную ошибку. Теперь `body: dict = {"items": []}` объявлен до `try`, мёртвый цикл убран;
уборка (children + контур) осталась в `finally`.

## 5. V1b-1: каскад ложных 401 (`ACCESS_TOKEN_TTL_MIN`)

Причина: access-токен живёт 15 минут, а полный прогон на медленной машине (или с одним
зависшим тестом) идёт дольше. Сессионный `admin_headers` начинает отдавать 401, и падает
всё подряд — на V1b один зависший тест превратился в 30 «падений».

Выбран вариант «отдельный TTL для тестов» (он же предложен в контракте): в `conftest.py`
**до импорта приложения** ставится

```python
os.environ.setdefault("ACCESS_TOKEN_TTL_MIN", "720")   # 12 часов — только в процессе pytest
```

и после импорта — fail-fast проверка, что настройка применилась:

```python
if settings.ACCESS_TOKEN_TTL_MIN < 60:
    raise RuntimeError("Для тестов нужен ACCESS_TOKEN_TTL_MIN >= 60 ...")
```

Почему TTL, а не «перелогин при 401»: перехват 401 в клиенте пришлось бы включать только
для запросов с сессионным токеном — иначе тесты, которые *ожидают* 401 (анонимные запросы),
получали бы 200, и проверки безопасности стали бы ложно-зелёными. TTL решает причину
(токен не истекает) без изменения семантики ответов; влияет только на процесс pytest,
прод-настройка не затрагивается.

## 6. V1b-2: защита от зависания

`pytest-timeout` в окружении **не установлен** (проверено), а `requirements.txt` — вне
объёма задачи, поэтому сторож сделан на stdlib:

```python
TEST_TIMEOUT_SECONDS = float(os.environ.get("TEST_TIMEOUT_SECONDS", "180"))

@pytest.fixture(autouse=True)
def guard_test_timeout():
    faulthandler.dump_traceback_later(TEST_TIMEOUT_SECONDS, repeat=False, exit=True)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()
```

Поведение: тест, зависший дольше 180 с, печатает стеки всех потоков и завершает процесс
(код возврата 1) — прогон «падает» с диагностикой, а не висит 50 минут. Лимит настраивается
`TEST_TIMEOUT_SECONDS`. Когда `pytest-timeout` появится в окружении, достаточно добавить
`timeout = 180` в `pytest.ini` — сторож можно будет убрать.

## 7. Результаты прогонов

Окружение: `karier_test_db` после канонического reset (585 активных объектов, 3737 активных
связей, 87 сотрудников, alembic `0014`). Между прогонами **reset не делался**.

| Прогон | Команда | Результат | Время |
|---|---|---|---|
| Топология, прогон 1 | `pytest -q tests/test_topology_api.py` | **13 passed**, exit 0 | 26.66 s |
| Топология, прогон 2 (без reset) | `pytest -q tests/test_topology_api.py` | **13 passed**, exit 0 | 27.07 s |
| Полный, прогон 1 | `pytest -q` | **188 passed, 3 skipped, 0 failed**, exit 0 | 292.40 s (4:52) |
| Полный, прогон 2 (без reset) | `pytest -q` | **188 passed, 3 skipped, 0 failed**, exit 0 | 270.97 s (4:30) |

**Состояние БД после двух полных прогонов — ровно как до них** (это и есть проверка, что
фикстура действительно чистит):

| Показатель | До прогонов | После двух прогонов |
|---|---|---|
| активных объектов (`gis.assets`) | 585 | **585** |
| активных связей (`gis.links`) | 3737 | **3737** |
| сотрудников (`auth.employees`) | 87 | **87** |
| из них с табельным `8XXXXX` | 41 | **41** |
| сотрудников `TST-*` (создаёт тест) | 0 | **0** |

Примечания:

* собрано **191 тест** (188 passed + 3 skipped) — не 173 из контракта: после S-8/S-4 набор
  вырос (`test_sync_api`, `test_security_ip` и др.). Три skip — предсуществующие, к уборке
  отношения не имеют;
* на первом заходе второй прогон топологии занял **40 минут** и дал 1 падение
  (`test_power_path_breaks_when_cell_off`): в это время параллельно шёл reset тестовой БД
  (её пересоздавал капитан), и тесты стояли на блокировках. После освобождения БД оба
  прогона топологии и оба полных прогона — чистые (таблица выше);
* время полного прогона стабильно: 4:52 и 4:30 (разница — кэш/прогрев), без роста между
  запусками — значит уборка не создаёт деградации.

## 8. Остаточные риски и что осталось за рамками

* **Параллельные прогоны запрещены.** Уборка и снимок PK рассчитаны на один процесс pytest:
  при двух одновременных прогонах на одной `karier_test_db` второй увидит чужие новые
  строки и удалит их (и сам получит ложные падения). Это ограничение зафиксировано в
  контракте V1 и остаётся в силе.
* **Что НЕ чистится:** `ops.inspections/defects/media`, `gis.map_layers`, `audit.audit_log`,
  `sync.*`. Эти таблицы не входят в согласованный порядок уборки; их рост не ломает
  уникальность, но объём БД растёт. Плюс media-файлы на диске (`backend-v2/var/media`)
  не удаляются вовсе. Кандидат на отдельную задачу «полная изоляция тестовой БД»
  (транзакционный rollback на тест или reset между прогонами).
* **`test_ux_api` и `?limit=1000`:** хелперы ищут демо-объекты в первой тысяче; при раздутой
  базе (V1: 1721–1950 объектов) они пропускали `KTP-14`/`POLE-3` → `StopIteration` и каскад
  29–32 падений. С уборкой база больше не растёт, но хрупкость остаётся: правильнее искать
  объект по коду (`?q=`/`type_code`), а не «первой тысячей». Отдельная задача.
* **Аудит-лог** продолжает расти от каждого прогона (append-only по смыслу системы) — на
  объём ответов `GET /api/audit?limit=` не влияет, на размер БД — да.

## 9. Команда повторного прогона (без reset БД)

```powershell
cd C:\karier\karier\backend-v2
.\venv\Scripts\python.exe -m pytest -q   # прогон 1
.\venv\Scripts\python.exe -m pytest -q   # прогон 2 — без test-db-reset
.\venv\Scripts\python.exe -m pytest -q tests/test_topology_api.py   # точечно, дважды
```

## 10. Изменённые файлы

| Файл | Характер |
|---|---|
| `backend-v2/tests/conftest.py` | `isolate_created_rows`, `guard_test_timeout`, TTL + fail-fast, импорты |
| `backend-v2/tests/test_topology_api.py` | `try/finally` вокруг проверки и уборки `Link` |
| `backend-v2/tests/test_line_builder.py` | `body` до `try`, мёртвый цикл убран |
| `backend-v2/tests/test_auth_api.py` | `TST-<uuid8>` + уборка сотрудника, импорт `text` |
| `docs/team/27-test-isolation.md` | этот отчёт |
