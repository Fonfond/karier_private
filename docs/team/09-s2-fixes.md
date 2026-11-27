# 09 — S-2: корректность последних правок (422, тест контура, restore, title, индекс)

Дата: 2026-11-24, 21:25–22:10 (локальное время машины, UTC+08:00).
Кто: `edit-reviewer`. Задача t8 (implementation), проект `C:\karier\karier`.
Исправления по отчёту `docs/team/05-edit-review.md` (риски R5, R4, R9, R10, R19).

## Сводка

| # | Дефект из ревью | Что сделано | Проверено |
|---|---|---|---|
| 1 | R5: в 422 русские подписи подменили машинные ключи `fields` | `fields` снова с машинными ключами (`name`, `type_code`, `x`…), подписи — в новом поле `field_labels`; `detail` остаётся русским | 3 новых теста контракта + mutation-проверка (на старом поведении тесты краснеют) |
| 2 | R4: литерал `\n` съел `assert` контура | строка разбита на комментарий + `assert` | AST: `Assert` на строке 94 функции; mutation: без контура в `nodes` тест падает именно на :94 |
| 3 | R9: `restore` не проверял архивного родителя | 409 `asset.parent_archived` до любых изменений | новый тест: 409 + успешный restore после возврата родителя — 200 |
| 4 | R10: `title` из пробелов проходил валидацию | проверка после `strip()` → 422 `schema_snapshot.title_empty`; обрезка по краям сохранена | 2 новых теста в `test_schema_snapshots.py` |
| 5 | R19: дрейф `ix_schema_snapshots_created` | индекс и `comment` таблицы снимков объявлены в метаданных (файл `app/models/topology.py`, как задано в inScope); сам `app/models/gis.py` не менялся | `alembic revision --autogenerate`: операций над `schema_snapshots` больше нет |
| 6 | — | новый файл `tests/test_api_contract_validation.py` | 3 теста, все зелёные |

Итог прогонов: **168 passed** (было 162; +3 контракт, +2 снимка, +1 restore-родитель), 0 failed;
`tsc -b --noEmit` — exit 0.

## 1. Контракт 422: машинные ключи + подписи (`app/main.py`)

Было (правки от 24.11):

```python
label = FIELD_LABELS.get(key, key)
fields[label] = _ru_validation_message(...)   # ключ «Название» вместо «name»
```

Стало:

```python
fields[key] = _ru_validation_message(...)         # «name», «type_code», «x» — контракт
field_labels[key] = FIELD_LABELS.get(key, key)    # «Название», «Тип», «X» — для UI
...
parts = [f"{field_labels[key]}: {message}" for key, message in fields.items()]
detail = parts[0] ...                             # читаемый русский текст
response = problem_response(..., fields=fields)    # единый формат problem+json
body = json.loads(response.body)
body["field_labels"] = field_labels                # подписи рядом, ключи не подменяются
return JSONResponse(status_code=422, content=body, media_type="application/problem+json",
                    headers={"X-Request-ID": response.headers.get("X-Request-ID", "")})
```

`field_labels` добавляется **только** в ответе обработчика валидации, в `main.py`
(файл `app/core/errors.py` и общий `problem_response()` не менялись — в `inScope`
его не было). Остальные ошибки (`ApiError`, `conflict`, `not_found`) отдают ровно то же,
что и раньше. Тело ответа берётся у `problem_response()`, чтобы не дублировать скелет
`type/title/status/code/detail/instance/request_id`; `content-length` не копируется —
`JSONResponse` пересчитывает его сам.

Ответ на `POST /api/assets` с `{"name": "", "type_code": "ktp"}` теперь:

```json
{
  "code": "validation.failed",
  "detail": "Название: минимум 2 символа",
  "fields": {"name": "минимум 2 символа"},
  "field_labels": {"name": "Название"}
}
```

Фронтенд-совместимость: `src-v2/src/lib/api.ts:41-57` читает `detail` (строка) и
`fields` (Record<string,string>) — оба на месте, `field_labels` клиент просто игнорирует
(лишний ключ в problem+json безопасен). Поле `fields` снова пригодно для подсветки
конкретного поля формы.

## 2. Живой assert контура (`tests/test_schema_builder.py:93-94`)

Было: `# ... и блоком\n    assert any(node["id"] == contour["id"] ...)` — утверждение
внутри комментария, не выполнялось.

Стало — две строки:

```python
    # контейнер обязан быть и узлом (иначе редактор его не отрисует), и блоком
    assert any(node["id"] == contour["id"] for node in graph["nodes"])
```

Доказательство, что проверка живая (mutation-прогон, файл восстановлен побайтово):
временно из `services/schema_graph.py` убран контур из `nodes` → тест падает ровно на
`tests/test_schema_builder.py:94` (`assert False`), после восстановления — снова зелёный.

## 3. Restore при архивном родителе (`app/services/gis.py:532-550`)

Перед любыми изменениями объекта:

```python
if asset.parent_asset_id is not None:
    parent = db.get(Asset, asset.parent_asset_id)
    if parent is not None and parent.deleted_at is not None:
        raise conflict(
            "Родительский объект находится в архиве — сначала верните его",
            "asset.parent_archived",
        )
```

Проверка стоит до `asset.deleted_at = None`, поэтому при 409 объект остаётся в архиве
(нет «полувосстановленного» состояния). Обычный путь не изменён: после возврата
родителя тот же ребёнок восстанавливается с 200 — это отдельное утверждение в тесте.

Новый тест `tests/test_schema_builder.py:208` `test_restore_child_of_archived_parent_conflicts`:
контур → ячейка → в архив ячейка, затем контур → restore ячейки = 409 `asset.parent_archived`
→ restore контура = 200 → restore ячейки = 200 → уборка.

## 4. Название снимка после strip (`app/services/schema_snapshots.py:55-68`)

```python
title = payload.title.strip()
if len(title) < 2:
    raise ApiError(422, "schema_snapshot.title_empty", "Название снимка — минимум 2 символа")
```

Причина дефекта: в схеме `SnapshotCreate.title` стоит `min_length=2` по **сырой** строке,
поэтому `"  "` проходил Pydantic. Теперь проверяется уже обрезанное значение и отвечает 422
(а не 500 и не пустая запись). Пробелы по краям по-прежнему обрезаются — и в `title`,
и в `comment`.

Тесты `tests/test_schema_snapshots.py`: `test_snapshot_title_whitespace_only_rejected` (422 +
код) и `test_snapshot_title_and_comment_are_trimmed`.

## 5. Индекс и комментарий таблицы снимков (`app/models/topology.py:145-155`)

```python
# --- снимки схемы: индекс и комментарий таблицы -----------------------------
# Сама таблица `gis.schema_snapshots` объявлена в `app.models.gis`, а её индекс по
# `created_at` и комментарий созданы миграцией 0014. Пока они не описаны в
# метаданных, `alembic revision --autogenerate` предлагает их удалить/пересоздать
# на каждом прогоне. Объявляем здесь — рядом с остальной топологией схемы.
SCHEMA_SNAPSHOT_COMMENT = (
    "Снимок схемы: состояние топологии на дату (черновик или опубликованная версия)"
)
SchemaSnapshot.__table__.comment = SCHEMA_SNAPSHOT_COMMENT
Index("ix_schema_snapshots_created", SchemaSnapshot.__table__.c.created_at)
```

`ix_schema_snapshots_created` создаётся миграцией `0014`, но не был объявлен в метаданных →
autogenerate предлагал его удалить. При проверке выяснилось, что тем же дефектом страдал
**комментарий таблицы** (миграция `0014` его задаёт, модель — нет): autogenerate предлагал
`drop_table_comment`/`create_table_comment` на `schema_snapshots`. Объявлено и то, и другое —
теперь операций над `schema_snapshots` в автогенерации нет.

Файл выбран по inScope задачи (`app/models/topology.py`); сам класс `SchemaSnapshot` живёт
в `app/models/gis.py:247`, и этот файл **не менялся** — объявление идёт через уже
существующий там объект таблицы (`topology.py` и так импортирует `SCHEMA` из `models.gis`,
поэтому циклического импорта не возникает).

## 6. Новый тест контракта (`tests/test_api_contract_validation.py`)

Три теста:

1. `test_invalid_name_keeps_machine_key_and_adds_label` — `fields == {"name": ...}`,
   `field_labels == {"name": "Название"}`, `"Название" not in fields`, `detail` русский;
2. `test_missing_type_and_broken_x_use_machine_keys` — ключи `type_code` и `x`, подписи
   «Тип»/«X» отдельно, `detail` сворачивает вторую ошибку в «и ещё 1»;
3. `test_problem_payload_stays_client_compatible` — форма ответа для фронтенда
   (`detail` строка, `fields`/`field_labels` — строковые словари, `status`, `title`, `request_id`).

**Проверено, что тесты краснеют при откате:** временно возвращено старое поведение
(`fields[label] = ...`), прогон `pytest -q tests/test_api_contract_validation.py` →
**3 failed**; после восстановления файла (sha256 совпал) — снова 3 passed.

## 7. Верификация

| Команда | Результат |
|---|---|
| `pytest -q tests/test_schema_builder.py tests/test_api_contract_validation.py tests/test_schema_snapshots.py` | **17 passed**, 28.58 s, exit 0 |
| `alembic revision --autogenerate -m tmp-check` (в обёртке из контракта) | exit **0**; по снимкам дрейфа нет (см. ниже) |
| `pytest -q` (полный набор) | **168 passed**, 0 failed, 505.76 s, exit 0 (прогон 21:38–21:47 — уже на финальном коде, до правок S-1) |
| `npm.cmd run typecheck` (`tsc -b --noEmit`) | exit **0** |
| `alembic current` (read-only) | `0014_schema_snapshots (head)` |

Повторная проверка на текущем дереве (после того как параллельная задача S-1 закоммитила
гигиену репозитория, см. §8.4): поднабор — **17 passed** (41.5 s); autogenerate — те же
6 предсуществующих расхождений, операций над `schema_snapshots` по-прежнему нет.

**Про повторный полный прогон (важно).** После коммита S-1 я перезапустил `pytest -q`
на текущем дереве: он шёл 24 мин (вместо 8.5) и дал 45 failed. Разбор:

* `pytest -q --lf` (только упавшие) → **37 passed, 1 failed** — то есть падения были
  следствием общего состояния БД в момент прогона, а не кода;
* единственное устойчивое падение — `tests/test_topology_api.py::test_cycle_detected_in_topology_issues`:
  тест вставляет `Link` напрямую в БД (`tests/test_topology_api.py:114-145`) и **не удаляет его**,
  поэтому повторный прогон упирается в `uq_links_pair_active`. В `karier_test_db` действительно
  осталась живая строка `gis.links` (`97ff0291…`, `busbar`, `created_at 22:15:34`) — след
  предыдущего прогона. Это **предсуществующий дефект изоляции тестов** (о нём же писал t3:
  «тесты оставляют данные в karier_test_db»), к правкам S-2 отношения не имеет;
* чтобы снова получить чистый зелёный полный прогон, нужно сбросить тестовую БД
  (`test-db-reset.cmd`) и (отдельной задачей) закрывать за собой связи в этом тесте —
  оба действия вне объёма S-2 (`tests/test_topology_api.py` не в inScope).

Фронтенд не менялся (`src-v2` вне правок), typecheck зелёный, `vite build` не запускался —
его результат от этих правок не зависит (бэкенд + тесты), по t3 он был зелёным.

## 8. Что осталось и требует отдельного решения

### 8.1 Autogenerate всё ещё не пуст — но это предсуществующий дрейф, не по снимкам

После исправления автогенерация по-прежнему показывает (проверено на `karier_db`,
которая стоит на `0014 (head)`):

* индексы есть в БД, но не объявлены в моделях: `ix_asset_types_parent` (`gis.asset_types`),
  `ix_assets_schema_block` (`gis.assets`), `ix_defects_active` (`ops.defects`),
  `ix_maintenance_at` (`ops.maintenance_entries`);
* внешние ключи объявлены в моделях, но отсутствуют в БД: `gis.assets.schema_block_id → assets.id`,
  `ops.defects.deleted_by → auth.employees.id`;
* комментарии таблиц: миграции их задают, модели — нет (~20 таблиц, `drop_table_comment` /
  `create_table_comment`).

Это не следствие правок от 24.11 и не входит в объём S-2 (потребуется либо новая миграция —
а значит изменение БД, — либо объявление комментариев/индексов во всех моделях). **Рекомендация:**
отдельная задача «привести модели в соответствие со схемой БД»; до неё `--autogenerate`
нельзя использовать как проверку «дрейфа нет».

### 8.2 Проверочная команда из контракта не ловит дрейф (баг в самой команде)

Alembic превращает сообщение `tmp-check` в имя файла с подчёркиванием
(`…_tmp_check.py`), а команда ищет `*tmp-check*` — шаблон никогда не совпадает, поэтому
команда всегда возвращает 0 и **оставляет** созданный файл миграции в `alembic/versions`.
Фактически: файл создаётся и после проверки удалён вручную; дрейф по снимкам проверен
отдельно — по содержимому сгенерированного файла (операций над `schema_snapshots` нет,
осталась только строка `Revises: 0014_schema_snapshots`).

Как правильно:
`if (Test-Path .\alembic\versions\*_tmp_check*) { Get-ChildItem .\alembic\versions\*_tmp_check* | Remove-Item -Force; exit 1 }`.

### 8.3 Отклонений от inScope нет

Все изменённые файлы входят в inScope задачи. Отдельно отмечу два места, где inScope
разошёлся с фактической раскладкой кода:

* `field_labels` собирается в `app/main.py` — `app/core/errors.py` **не менялся**
  (в inScope его не было, поэтому общий `problem_response()` оставлен как есть);
* индекс и комментарий таблицы снимков объявлены в `app/models/topology.py` (как указано
  в inScope), хотя класс `SchemaSnapshot` живёт в `app/models/gis.py`; этот файл
  **не менялся** — он побайтово равен исходной версии (12 259 байт).

### 8.4 Параллельные изменения в репозитории (не мои)

Пока шла задача, смежная задача S-1 («гигиена репозитория») закоммитила изменения
(`backend-auditor`, HEAD `8e94446e`: «renormalize line endings» + «убрать пароль БД и
dev-секреты из кода»), переписав `.git/index` (21:49) и изменив `tests/conftest.py`
(21:42 — DSN тестовой БД теперь из `TEST_DATABASE_URL`/`tests/.env.test`, пароля в коде нет),
`app/core/config.py` и `.gitignore`. Эти файлы **вне моего объёма, я их не трогал**.
После коммита перепроверено: все мои правки на месте (`main.py:156-196`,
`models/topology.py:145-155`, `services/gis.py:545`, `schema_snapshots.py:63`,
`test_schema_builder.py:94`), поднабор тестов зелёный, дрейф по снимкам отсутствует.

Два практических замечания капитану:
* полный прогон `pytest -q` (168 passed) шёл, когда `conftest.py` был ещё в старой редакции:
  тестовая инфраструктура менялась параллельно. Результат подтверждён повторным прогоном
  поднабора уже на новом `conftest.py` (17 passed);
* нумерация строк в файлах, затронутых коммитом S-1, могла сдвинуться — все ссылки в отчёте
  проверены после него.

## 9. Ограничения соблюдены

* `tests/conftest.py`, `app/core/config.py`, `app/core/errors.py`, `app/models/gis.py`,
  `backend-v2/.env`, `src-v2` — **не тронуты** (изменения в `conftest.py`/`config.py` сделаны
  задачей S-1, см. §8.4; `models/gis.py` побайтово возвращён к исходной версии после
  промежуточной правки — 12 259 байт).
* Рабочая БД `karier_db` не изменялась: только read-only `alembic current` и рефлексия схемы
  при `--autogenerate` (никаких DDL/DML); тесты работают на `karier_test_db` (изоляция в conftest).
* Временные mutation-прогоны (2 шт.) откатывались побайтово — sha256 файлов до и после совпал.
* Созданные проверкой файлы миграций удалены; в `alembic/versions` остались только 14 штатных.
* Временные файлы: только в `%TEMP%`, в репозиторий не попадали.

## 10. Перечень изменённых файлов

| Файл | Характер |
|---|---|
| `backend-v2/app/main.py` | машинные ключи `fields`, `field_labels`, русский `detail` |
| `backend-v2/app/services/gis.py` | 409 `asset.parent_archived` в `restore_asset` |
| `backend-v2/app/services/schema_snapshots.py` | проверка `title` после strip → 422 |
| `backend-v2/app/models/topology.py` | `Index("ix_schema_snapshots_created")` + `comment` таблицы снимков (по inScope) |
| `backend-v2/tests/test_schema_builder.py` | разбит «склеенный» assert; новый тест restore-родителя |
| `backend-v2/tests/test_schema_snapshots.py` | 2 теста: пустой и обрезанный `title` |
| `backend-v2/tests/test_api_contract_validation.py` | новый файл, 3 теста контракта 422 |
| `docs/team/09-s2-fixes.md` | этот отчёт |
