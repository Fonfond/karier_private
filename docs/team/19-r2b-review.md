# 19 — R2b: перепривязка ревью S-2 к текущим байтам

**Дата:** 2026-11-25 (поздний вечер, UTC+08)
**Ревьюер:** backend-auditor (задача t31, команда karier-improvements)
**Предмет:** вердикт R2 (`docs/team/13-r2-review.md`, t12) перепривязывается к актуальным байтам после гигиенических правок (S-1c/S-3b) и последующих волн (S-4, S-9).
**Режим:** read-only (хеши, чтение кода, `git grep`, `alembic heads/check`); pytest-поднабор — после эксклюзивного окна V1c (см. §6). Ничего не исправлялось; изменён только этот отчёт.

## Вердикт: **pass** (S-2-сущность не деградировала; delta в `tests/` — от S-4/S-9/S-3 и S-2-тестов не касается — см. §2)

| Критерий приёмки | Результат |
|---|---|
| Delta с момента R2: только `.gitignore`/`requirements.txt` | **частично**: `.gitignore` и `requirements.txt` действительно изменились (S-1c/S-3b), но в `tests/` и `app/` есть правки поздних волн (S-4, S-9, S-3) — перечислены в §2. S-2-файлы не менялись. |
| `app/main.py` и тесты S-2 не менялись | **да**: `app/main.py`, `tests/test_api_contract_validation.py`, `test_schema_builder.py`, `test_schema_snapshots.py`, `test_undo_restore.py` — mtime до вердикта R2 (2026-11-25 11:56), байты те же, что проверялись в R2. `tests/` в целом менялся (S-4/S-9) — не S-2. |
| Контракт 422 по-прежнему `fields` + `field_labels` | **да**: `app/main.py` (sha256 `A92DD35B…`) не менялся с R2; live-проверка §3 подтверждает. |
| Live-проверка 422 проходит | **да** — см. §3 (поля сверены побайтово по JSON). |
| pytest поднабор `contract + schema_builder + schema_snapshots` зелёный | **да**: 33 passed, 47.84 с, exit 0 (плюс sync-тесты S-4 в том же прогоне — по указанию капитана). |
| Автогенерация baseline не изменилась | **да**: голова `0014_schema_snapshots`; `alembic check` → те же **29** предсуществующих операций (23 `remove_table_comment`, 4 `remove_index`, 2 `add_fk`), **0** по `schema_snapshots`. |

## 1. Байты (актуальные)

Digest деревьев — по методике V1b/V1c (все `*.py`, сортировка, `sha256:путь`, sha256 от склейки):

| Объект | Значение |
|---|---|
| `backend-v2/app/` (74 файла) | `5c508ec591bbcbb81295dd9e9dc04aaf6eca59344097b07735740badf50b0943` |
| `backend-v2/tests/` (31 файл) | `f1f67baf22c58337925d5ee7657ca4e8317d52dfcff5397585a940010e4faa6a` |
| `.gitignore` | `D78E761BDF40403518FF6C5B22B03086E6463522C74EE2A5349DAAD081A648E8` |
| `backend-v2/requirements.txt` | `730C6F0A57D2788BB649E82DAD74E1FF5D20AF79A002D58C77C3D3FB600566A8` |
| `backend-v2/app/services/gis.py` | `A0F1E574E81832390BD4095926E03BF7BE8A64BAF37AF20F70C702BD874F4C06` |

Сверка с независимым замером QA (V1c, `C:\karier\.tmp\qa-v1c\v1c-sequence.log`, M1): `app=5c508ec5… (74)`, `tests=f1f67baf… (31)`, `gi=D78E761B…`, `rq=730C6F0A…`, `gis.py=A0F1E574…` — **совпадает до символа**.

Изменения относительно снимка V1b (`app=12a39bb2…`, `tests=b3815f42…`, 30 файлов) предсказуемы: S-4 (3 файла `app/` + `tests/test_sync_api.py` + новый `test_security_ip.py` → 31-й файл) и S-9 (тесты изоляции).

## 2. Фактическая delta с момента R2 (`mtime > 2026-11-25 11:56`)

| Файл | mtime | Волна |
|---|---|---|
| `tests/test_migrations.py` | 14:53 | S-3 |
| `.gitignore`, `requirements.txt` | 14:55 | S-1c/S-3b (гигиена) |
| `app/core/config.py`, `app/core/rate_limit.py`, `app/services/sync.py` | 20:25 | S-4 |
| `tests/test_security_ip.py` (новый), `tests/test_sync_api.py` | 20:25–20:26 | S-4 |
| `tests/conftest.py`, `tests/test_topology_api.py`, `tests/test_line_builder.py` | 20:25–20:26 | S-9 |
| `tests/test_auth_api.py` | 22:19 | S-9 |

Файлы S-2 (все — mtime до R2, не менялись):

| Файл | sha256 |
|---|---|
| `app/main.py` | `A92DD35BB6F0E8AA40AE5DDAD988E406986742AA3C74F8D19F0DB0E012791772` |
| `app/core/errors.py` | `DE3A10DEF662D529D323B9D2930858E8DE771EDE3019F80A78A4EB2B21F34EE5` |
| `app/models/topology.py` | `4876AE88799522F0083CB523E9770C6D458677D286ECB0AC25311142565B7098` |
| `app/models/gis.py` | `C54E6859ADF16FCE7FD63F676AA51A1C82E9590B306E2108E9943E5FC239AAC9` |
| `app/services/schema_snapshots.py` | `A1924082578F3B0F9328CBC00467EF575439570F72B9206C25ECCFB120FE3EEA` |
| `tests/test_api_contract_validation.py` | `B2E31727BD4266CB524AEAB51A24B28779CEC8051D3422675BD54B6AF93BF595` |
| `tests/test_schema_builder.py` | `736B25DC4B788E0452E44BC5A80895F5EF39488D5CF64372ED21FC6A062AD363` |
| `tests/test_schema_snapshots.py` | `3FD5802608C37E94373D2C8D47281C30591FB9A988F0BD2266BA5C1F87ED72CB` |
| `tests/test_undo_restore.py` | `96EB1CB1A1961DB743167E6BE24E8AE821B6B5BCA60C64690650C7AC59E15245` |
| `alembic/versions/0014_schema_snapshots.py` | `2817C27B3A9B5F29F04093E95743B0125AAC547C4C3D32899361EF0BC8210AC2` |

Вывод: **ни один файл, на котором держится вердикт R2, не менялся**. Правки S-4/S-9 касаются других файлов и других предметов (RBAC/аудит и изоляция тестов); контракт 422, тест контура, restore/409, title и объявление индекса/комментария снимков — в тех же байтах.

## 3. Live-проверка контракта 422 (рабочий API 8001, `karier_db`)

```http
POST /api/assets  {"name":"","type_code":"ktp"}
→ HTTP 422, content-type: application/problem+json
{"code":"validation.failed","fields":{"name":"минимум 2 символа"},
 "field_labels":{"name":"Название"},"detail":"Название: минимум 2 символа", …}
```

`field_labels` присутствует, ключи `fields` машинные, `detail` русский — как в R2. Запрос отклонён валидацией, данные не менялись.

## 4. Тесты S-2: состав и байты

`tests/test_api_contract_validation.py` (3 теста), `test_schema_builder.py` (контур/restore), `test_schema_snapshots.py` (title/trim) — байты из §2, mtime до R2. С момента R2 эти файлы не редактировались; S-9 меняла `conftest.py` (изоляция) и другие тесты, но не S-2-файлы.

## 5. Autogenerate baseline

* `alembic heads` → `0014_schema_snapshots (head)` — одна голова.
* `alembic check` (read-only, `karier_db`) → exit 1 (ожидаемо), ровно **29** операций: `remove_table_comment` ×23, `remove_index` ×4 (`ix_asset_types_parent`, `ix_assets_schema_block`, `ix_defects_active`, `ix_maintenance_at`), `add_fk` ×2 (`gis.assets.schema_block_id`, `ops.defects.deleted_by`).
* Операций по `schema_snapshots` — **0**; `ix_schema_snapshots_created` и комментарий таблицы присутствуют и в метаданных (`app/models/topology.py`, байты R2), и в БД.
* Модели `models/gis.py`, `models/topology.py` и миграция `0014` — mtime/hash из §2, не менялись после R2 ⇒ baseline S-3 (29 операций) остаётся верным.

## 6. Прогон поднабора (после «R2b можно», V1c закрыта)

```
pytest -q tests/test_api_contract_validation.py tests/test_schema_builder.py \
         tests/test_schema_snapshots.py tests/test_sync_api.py
→ 33 passed, 504 warnings in 47.84s, exit 0
```

Покрытие прогона: контракт 422 (3), тест контура и restore/409 (`test_schema_builder`), title/trim (`test_schema_snapshots`), sync-RBAC и границы (S-4). Полный `pytest -q` не запускался — V1c на этих же байтах дала 188 passed ×2.

**Live 422 (рабочий API 8001, `karier_db`, invalid-запрос отклонён до записи):**

```json
{"code":"validation.failed","detail":"Название: минимум 2 символа",
 "fields":{"name":"минимум 2 символа"},"field_labels":{"name":"Название"}}
```
`/api/health/ready` → `{"status":"ok","database":"ok"}`.

**Хеши до/после прогона (гарантия привязки вердикта):**

| Объект | До прогона | После прогона |
|---|---|---|
| `app/` (74) | `5c508ec591bbcbb81295dd9e9dc04aaf6eca59344097b07735740badf50b0943` | **тот же** |
| `tests/` (31) | `f1f67baf22c58337925d5ee7657ca4e8317d52dfcff5397585a940010e4faa6a` | **тот же** |
| `.gitignore` | `D78E761B…A648E8` | **тот же** |
| `requirements.txt` | `730C6F0A…0566A8` | **тот же** |

Совпадает с QA V1c (M1): вердикт привязан к текущим байтам, прогон их не менял (изоляция S-9 работает).

## 7. Оговорки

1. Формулировка «delta только .gitignore/requirements.txt» неточна: после R2 в `tests/` прошли S-3 (test_migrations), S-4 (sync/security) и S-9 (изоляция) — см. §2. S-2-файлы не менялись, поэтому вердикт R2 перепривязывается корректно.
2. `app/services/gis.py` с момента R2 не менялся (`A0F1E574…`, S-8 завершилась до R2) — уже входил в вердикт R2.
3. Baseline S-3 проверяет только «новые» расхождения; 29 предсуществующих — по-прежнему ожидаемы до S-10.
4. Live-проверка 422 выполнена на рабочей БД только чтением (невалидный запрос); `karier_test_db` не затрагивалась.
