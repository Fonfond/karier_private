# 13 — R2: ревью S-2 (контракт 422, живой assert контура, restore/409, title, autogenerate)

**Дата:** 2026-11-25
**Ревьюер:** backend-auditor (задача t12, команда karier-improvements)
**Предмет ревью:** S-2 (t8) — отчёт `docs/team/09-s2-fixes.md`, код и тесты в рабочем дереве.
**Режим:** только чтение и запуск проверок. Код, тесты, модели, миграции не изменялись; рабочая БД `karier_db` — только read-only (`alembic check`, `psql`-чтение), тесты — на `karier_test_db`. Временная runtime-мутация сделана внешним pytest-плагином вне репозитория (`C:\karier\tools\mutation_plugin.py`), файлы проекта не трогались.

## Вердикт: **pass** (с оговорками C1 и наблюдениями O1–O5; все они — предсуществующие/вне объёма S-2, вынесены в S-9/S-10)

| # | Критерий приёмки | Результат | Доказательство |
|---|---|---|---|
| 1 | `fields` содержит машинные ключи, `field_labels` — подписи | **выполнен** | `app/main.py:156-196`; live-проверка: `fields={"name": …}`, `field_labels={"name":"Название"}`, `detail="Название: минимум 2 символа"`; тесты `tests/test_api_contract_validation.py:23-74` |
| 2 | Фронтенд не сломан (`tsc`/`build` зелёные) | **выполнен** | `npm run typecheck` → exit 0 (11.7 с); `npm run build` → exit 0 (19.6 с, известное предупреждение о чанке >500 кБ); контракт читается в `src-v2/src/lib/api.ts:35-60` (`detail`, `fields`), `field_labels` клиент игнорирует |
| 3 | assert контура выполняется: при удалении проверки тест падает | **выполнен** | AST: `Assert` на `tests/test_schema_builder.py:94`; runtime-мутация (контур убран из `nodes` внешним плагином) → `FAILED … test_schema_builder.py:94`; без мутации — 1 passed |
| 4 | restore при архивном родителе → 409; успешный restore → 200 | **выполнен** | `app/services/gis.py:549-555` (проверка до всех мутаций); тест `tests/test_schema_builder.py:208-239` (409 + `asset.parent_archived` → 200 после возврата родителя); прогон теста отдельно — 1 passed |
| 5 | `title='  '` → 422, нормальный title сохраняется (с обрезкой) | **выполнен** | `app/services/schema_snapshots.py:59-63`; live: POST `/api/topology/snapshots` с `{"title":"   "}` → 422 `schema_snapshot.title_empty`; тесты `tests/test_schema_snapshots.py:106-116` (422 + trim) |
| 6 | Alembic autogenerate пуст, голова одна | **выполнен по снимкам, но не глобально** | голова одна (`0014_schema_snapshots`); `alembic check` → 29 предсуществующих операций, **ни одной** по `schema_snapshots`; `ix_schema_snapshots_created` и комментарий таблицы теперь объявлены в метаданных и присутствуют в БД. См. оговорку C1 |

## 1. Контракт 422: машинные ключи + подписи

Прочитано `app/main.py:156-196`: ключ `fields` строится из `loc` (машинное имя поля), подпись — в отдельный `field_labels`; `detail` собирается из подписей (читаемый русский текст), при нескольких ошибках — «(и ещё N)»; тело берётся у общего `problem_response()` и дополняется `field_labels`, поэтому `app/core/errors.py` не менялся, формат `problem+json` сохранён, `X-Request-ID` пробрасывается.

Независимая live-проверка на работающем API (`karier_db`, invalid-запрос отклонён до записи):

```http
POST /api/assets  {"name":"","type_code":"ktp"}
→ HTTP 422, content-type: application/problem+json
{
  "code": "validation.failed",
  "detail": "Название: минимум 2 символа",
  "fields": {"name": "минимум 2 символа"},
  "field_labels": {"name": "Название"},
  "status": 422, "request_id": "…"
}
```

Тесты контракта (`tests/test_api_contract_validation.py`) проверяют три вещи: машинный ключ `name` (и отсутствие «Название» в `fields`), пару `type_code`+`x` с подписями «Тип»/«X» и «и ещё 1» в `detail`, клиентскую форму ответа (`detail` — строка, `fields`/`field_labels` — `Dict[str,str]`, `status`, `title`, `request_id`). Прогон: **3 passed** в составе поднабора (ниже). Мутационная проверка автора (возврат старого поведения → 3 failed) правдоподобна и не противоречит коду; повторно не выполнялась (см. §7).

Фронтенд: `src-v2/src/lib/api.ts:35-60` читает `detail` и `fields`; `field_labels` — лишний ключ, который клиент игнорирует. `tsc -b --noEmit` и `vite build` — exit 0.

## 2. Живой assert контура

`tests/test_schema_builder.py:93-94`:

```python
# контейнер обязан быть и узлом (иначе редактор его не отрисует), и блоком
assert any(node["id"] == contour["id"] for node in graph["nodes"])
```

AST-разбор подтверждает, что это `ast.Assert` на строке 94 (не текст комментария); строк с литералом `\n` и `assert` в файле нет. Для независимого доказательства «живости» сделана **runtime-мутация без правки файлов**: pytest-плагин вне репозитория подменяет `schema_graph.build_graph_out` и выкидывает контур из `nodes`:

| Прогон | Результат |
|---|---|
| `pytest tests/test_schema_builder.py::test_contour_creates_registry_asset_and_block -p mutation_plugin` | **1 failed**, трейс `tests\test_schema_builder.py:94: AssertionError` |
| тот же тест без плагина | **1 passed** |

Это воспроизводит mutation-проверку автора (`09-s2-fixes.md:80-82`) и подтверждает, что проверка выполняется.

## 3. restore при архивном родителе → 409

`app/services/gis.py:541-583`: проверка `parent.deleted_at is not None` стоит **до** `asset.deleted_at = None`, поэтому при 409 «полувосстановленного» объекта не возникает; код ошибки — `asset.parent_archived` (409, `conflict`). Обычный путь не изменён: после возврата родителя ребёнок восстанавливается с 200.

Тест `tests/test_schema_builder.py:208-239`: контур → ячейка → обе в архив → restore ребёнка = 409 + `asset.parent_archived` → restore родителя = 200 → restore ребёнка = 200. Отдельный прогон: **1 passed**. То, что после 409 ребёнок остался в архиве, проверяется неявно: следующий `restore` ребёнка идёт через `get_archived_asset` (404, если объект уже не в архиве), и тест зелёный.

## 4. `title` из пробелов → 422

`app/services/schema_snapshots.py:59-63`: `title = payload.title.strip()`, затем `len(title) < 2` → `ApiError(422, "schema_snapshot.title_empty")`. Причина дефекта (Pydantic `min_length=2` по сырой строке) устранена; `comment` также обрезается (строка 69).

Live: POST `/api/topology/snapshots` с `{"title":"   "}` → **422**, `code=schema_snapshot.title_empty`, `content-type: application/problem+json`, запись не создаётся.
Тесты `tests/test_schema_snapshots.py:106-116`: отклонение пробельного title и обрезка `"  План сети на 24.11  "` → `"План сети на 24.11"`, `comment` — аналогично. Прогон: passed.

## 5. Autogenerate и голова

Проверка метаданных (read-only):

```python
SchemaSnapshot.__table__.comment == "Снимок схемы: состояние топологии на дату (…)"
indexes: ['ix_schema_snapshots_created', 'ix_schema_snapshots_pit_status']
```

В БД (`gis.schema_snapshots`, `karier_db`) присутствуют и `ix_schema_snapshots_created`, и комментарий таблицы — то есть объявления в `app/models/topology.py:146-155` совпадают со схемой.

`alembic heads` → `0014_schema_snapshots (head)` — одна голова.
`alembic check` (read-only) → **exit 1**, 29 операций, **ни одной** по `schema_snapshots`:
4 × `remove_index` (`ix_asset_types_parent`, `ix_assets_schema_block`, `ix_defects_active`, `ix_maintenance_at`), 2 × `add_fk` (`gis.assets.schema_block_id`, `ops.defects.deleted_by`), 23 × `remove_table_comment` (audit/auth/gis/ops).

Вывод: **дрейф по снимкам устранён** (цель S-2), но глобально autogenerate **не пуст** — см. C1. Это же зафиксировано в V1 (`docs/team/11-v1-acceptance.md`) и отнесено к S-10.

## 6. Как проверялось

| Команда | Результат |
|---|---|
| `pytest -q tests/test_api_contract_validation.py tests/test_schema_builder.py tests/test_schema_snapshots.py` | **17 passed**, 39.66 s, exit 0 |
| `pytest -q tests/test_schema_builder.py::test_restore_child_of_archived_parent_conflicts` | **1 passed**, exit 0 |
| `pytest …::test_contour_creates_registry_asset_and_block` + runtime-мутация (внешний плагин) | **1 failed** на `:94` (ожидаемо) |
| тот же тест без мутации | **1 passed** |
| live `POST /api/assets` (невалидное имя) | 422, `fields.name`, `field_labels.name`, русский `detail`, `problem+json` |
| live `POST /api/topology/snapshots` (`title="   "`) | 422 `schema_snapshot.title_empty` |
| `npm run typecheck` (`tsc -b --noEmit`) | exit 0, 11.7 с |
| `npm run build` (`tsc -b && vite build`) | exit 0, 19.6 с (warning: чанк >500 кБ — известен) |
| `alembic heads` | `0014_schema_snapshots (head)` |
| `alembic check` | exit 1: 29 предсуществующих операций, по `schema_snapshots` — 0 |
| Полный `pytest -q` | не перезапускался этим ревью; по V1 — **173 passed** дважды, каждый после `test-db-reset.cmd` |

## 7. Оговорки и наблюдения (не требуют доработки S-2)

**C1 (medium, предсуществующее, предусловие S-10).** Критерий «autogenerate пуст» глобально не выполнен: 29 операций (4 индекса, 2 FK, 23 комментария таблиц) — расхождение моделей и БД, существовавшее до правок 24.11. S-2 устранил только свою часть (снимки) и не мог закрыть остальное: это потребовало бы миграции (в out-of-scope S-2) либо правки чужих моделей. Зафиксировано в `09-s2-fixes.md:197-213`, V1 и относится к S-10. До S-10 `--autogenerate` нельзя использовать как проверку «дрейфа нет»; в этом ревью вместо него применён `alembic check` (читает и сравнивает, ничего не пишет).

**O1 (low, предсуществующее).** Для синтаксически битого JSON `RequestValidationError` даёт `loc=("body", 1)`, и после фильтрации `body` ключом становится `"1"`: `fields={"1": "не удалось разобрать JSON…"}`, `field_labels={"1": "1"}`, `detail="1: не удалось разобрать JSON…"`. Машинный ключ «1» бесполезен фронту. Это не регрессия S-2 (ключ и раньше строился из `loc`), но кандидат в S-9/S-10: спец-обработка `json_invalid` с ключом `body`/`_schema`.

**O2 (low).** `field_labels` добавляется только в обработчик `RequestValidationError`. Ручные `ApiError(422, ..., fields={...})` (например, `asset.out_of_bounds`, политика пароля) отдают только `fields` без подписей. Контракт «подписи — отдельно» для них не заявлен, фронтенд `field_labels` игнорирует, поэтому поломки нет; при желании — унифицировать в S-9.

**O3 (low).** Проверочная команда из контракта S-2 (поиск `*tmp-check*` в `alembic/versions`) не ловит дрейф: alembic создаёт файл `…_tmp_check.py` (подчёркивание), шаблон не совпадает, команда всегда возвращает 0 и оставляет файл. В этом ревью использован `alembic check`; в S-2 этот дефект уже описан (`09-s2-fixes.md:215-225`) — стоит заменить команду в шаблоне приёмки.

**O4 (low, предсуществующее, S-9).** Изоляция тестов: часть тестов оставляет строки в `karier_test_db` (связи/объекты), из-за чего повторные полные прогоны нестабильны; для чистого прогона нужен `test-db-reset.cmd`. В V1 это вынесено в S-9; к S-2 отношения не имеет.

**O5 (info).** Индекс и комментарий снимков объявлены в `app/models/topology.py` как побочный эффект импорта (правка метаданных класса из другого модуля). Это соответствует inScope S-2 и работает, потому что `app/models/__init__.py` импортирует `topology`; при изменении порядка импортов/точечном импорте `app.models.gis` объявления могут не примениться. Альтернатива на будущее — держать декларации в `models/gis.py` рядом с классом (в S-2 файл был вне inScope).

## 8. Границы ревью

* Изменённых файлов нет: ревью ничего не исправляло. Плагин мутации и вспомогательные скрипты лежат в `C:\karier\tools` (вне репозитория).
* Полный `pytest -q` не перезапускался (чтобы не создавать новые данные в тестовой БД в период V1/S-9); опираюсь на два прогона V1 (173 passed каждый после reset) и собственный поднабор 17 passed.
* Мутационная проверка S-2 (красные тесты при откате `fields` и при удалении контура из `nodes`) подтверждена косвенно: кодом, AST и runtime-мутацией контура; повторная мутация `fields` не делалась, т.к. требовала бы правки `app/main.py` (запрещено режимом ревью).
* `app/models/gis.py` в рабочем дереве отличается от HEAD (незакоммиченные правки владельца), поэтому «побайтовое равенство» из отчёта S-2 независимо подтвердить нельзя; проверено содержательно: S-2-специфичных объявлений (`ix_schema_snapshots_created`, `comment`) в этом файле нет — они в `models/topology.py`, как и заявлено.
