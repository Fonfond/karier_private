# 35c — Этап 3 / QA: тесты связей через ячейки, размеров и координат

**Дата:** 2026-11-27 (MSK)
**Задача:** t3 «Этап 3 / qa_agent: тесты связей через ячейки, размеров и координат»
**Ветка работ:** `db_agent → ui_agent → qa_agent` (этап 3 «Продвинутая интерактивность схемы»)
**Изменения:** только тесты и этот отчёт. `backend-v2/app` и `src-v2` не менялись.

## 1. Итог

| Проверка | Результат |
|---|---|
| Новый файл `backend-v2/tests/test_schema_interactivity.py` (7 тестов) | `7 passed` |
| Полный прогон `pytest -q` на `karier_test_db` | **`234 passed, 3 skipped, 0 failed`** (349.35 с) |
| Baseline до этапа 3 (35a) | 227 passed, 3 skipped |
| Прирост | +7 тестов, падений нет; 227 прежних тестов не сломаны |
| Состояние `karier_test_db` после прогона | 5049 объектов / 12965 портов / 3788 связей, rev `0017_schema_block_size` — как до прогона |
| Рабочая `karier_db` | не открывалась (conftest изолирует DSN на `karier_test_db`) |

## 2. Контракт t3 → покрытие

| Критерий приёмки | Тест | Статус |
|---|---|---|
| `POST /api/links` с портом вложенной ячейки: внешний объект → ячейка БКРУ = 201 | `test_links_accept_ports_of_nested_cells` | ✅ |
| `POST /api/links` ячейка → ячейка = 201 (jumper внутри блока попадает в `blocks[].jumpers`) | `test_links_accept_ports_of_nested_cells` | ✅ |
| Связь блок → блок по-прежнему 201 | `test_links_accept_ports_of_nested_cells` | ✅ |
| Несуществующий порт → 404, архивный → 422 `link.asset_archived`, чужой карьер → 404 | `test_links_reject_unknown_archived_and_foreign_ports` | ✅ |
| `PUT /api/topology/layout` с `width/height` блока сохраняет `schema_width/height`, граф отдаёт их | `test_layout_block_size_saved_and_returned_by_graph` | ✅ |
| `PUT` с `local_x/local_y` ячейки сохраняет `schema_local_x/y` | `test_layout_cell_local_coordinates_saved` | ✅ |
| Координаты вне `0…width/height` → 422; частично некорректный payload раскладку не меняет | `test_layout_rejects_bad_geometry_atomically` | ✅ |
| Автосейв-совместимость: серия ≥10 PUT, версии/`updated_at` незатронутых объектов не меняются, ошибок/таймаутов нет | `test_layout_autosave_series_touches_only_sent_assets` | ✅ |
| Регресс toggle/кабелей: on/off и install/return работают | `test_toggle_and_cable_regression_after_stage3` | ✅ |
| Полный `pytest -q`: 0 failed, passed ≥227 | §4 ниже | ✅ (234 passed) |
| Отчёт с хешами | этот файл, §5 | ✅ |

## 3. Что именно закреплено в тестах

Файл: `backend-v2/tests/test_schema_interactivity.py` (785 строк, 34 989 байт).
Блоки/объекты создаются «с нуля» через `POST /api/schema/composite` и `POST /api/assets` с
уникальными кодами (`QA3-*`), seeded-данные не изменяются; после теста созданные строки убирает
`isolate_created_rows` из `tests/conftest.py` (проверено: `QA3*` в БД после прогона — 0).
«Чужой карьер» создаётся напрямую в БД как неактивный `gis.pits` + объект + порт и удаляется в
`finally` (`qa3-*` в БД после прогона — 0).

### 3.1 Связи через порты вложенных ячеек

`test_links_accept_ports_of_nested_cells`:
* создаются два БКРУ-блока и внешний объект `yaku` (6 кВ, порты `IN-1`/`OUT-1`);
* `POST /api/links` внешний `OUT-1` → `IN-1` ячейки БКРУ → **201**; ответ содержит
  `from_asset.id` внешнего объекта, `to_asset.id` **вложенной ячейки**, коды портов,
  `link_type`, `feed_role`, `state=connected`;
* `POST /api/links` ячейка `OUT-1` → ячейка `IN-1` того же блока (`link_type=jumper`) → **201**;
  граф отдаёт перемычку в `blocks[].jumpers` (`from_cell_id`/`to_cell_id`);
* `POST /api/links` блок `OUT-1` → блок `IN-1` → **201** (прежний сценарий не сломан);
* в БД каждая связь лежит ровно на запрошенных портах (`from_port_id`/`to_port_id`), `deleted_at is null`;
* `GET /api/topology/graph` содержит все три ребра, ребро к вложенной ячейке имеет
  `to_asset_id = id ячейки`, все 6 ячеек остаются в `blocks[].children`.

`test_links_reject_unknown_archived_and_foreign_ports`:
* несуществующий `from_port_id` и несуществующий `to_port_id` → **404** `resource.not_found`
  (`application/problem+json`, `status`, `code`, `detail`);
* объект `yaku` удалён через `DELETE /api/assets/{id}` (мягко, `deleted_at`), затем связь с его
  `OUT-1` → **422** `link.asset_archived`, в `detail` есть слово «архив»;
* порт объекта другого карьера (`gis.pits.is_active=false`) → **404** `resource.not_found`;
* после всех отказов на порту ячейки нет ни одной живой связи (`count(*) = 0`).

### 3.2 Размер блока

`test_layout_block_size_saved_and_returned_by_graph`:
* только что созданный блок этапа 2 отдаётся графом с `schema_width/schema_height = null`
  и `width/height = null` (клиент рисует дефолт 320×220 — поведение не меняли);
* `PUT {"items":[{"asset_id":БЛОК,"width":520,"height":360}]}` → **200**,
  `updated=1, updated_blocks=1, updated_cells=0, updated_ports=0, skipped=[]`;
* в БД `gis.assets.schema_width=520`, `schema_height=360`;
* `GET /api/topology/graph` → `schema_width=520`, `schema_height=360` **и** совместимые
  `width=520`, `height=360` (снимки/PDF читают те же поля);
* `GET /api/assets/{id}` (`AssetOut`) тоже отдаёт `schema_width/schema_height`;
* ячейки после ресайза не «съехали»: `children[]` до и после PUT имеют одинаковые
  `(local_x, local_y)` — бэкендовая страховка требования «вёрстка блока при ресайзе не съезжает».

### 3.3 Координаты ячеек

`test_layout_cell_local_coordinates_saved`:
* блок получает размер 480×320, затем `PUT local_x=180.5, local_y=120.25` для ячейки → **200**,
  `updated=1, updated_cells=1, updated_blocks=0, skipped=[]`;
* в БД `schema_local_x=180.5`, `schema_local_y=120.25`; `schema_width` ячейки остался `null`
  (размер и локальные координаты не перепутаны);
* граф `blocks[].children[]` и `AssetOut` отдают те же значения;
* соседняя ячейка сохранила свои `(300.0, 140.0)` — меняется только переданный объект;
* границы включительно: `local_x == width (480)`, `local_y == height (320)` → 200;
  `local_x = local_y = 0` → 200.

### 3.4 Валидация и атомарность раскладки

`test_layout_rejects_bad_geometry_atomically` (блок 480×300, ячейка 60/140):
* `local_x=481` → **422** `layout.out_of_bounds`, в `detail` и `fields.local_x` есть «480»;
* `local_y=-1` → **422** `layout.out_of_bounds`, в `detail` «отрицательная»;
* после обоих отказов слепок объекта в БД (раскладка, размер, `version`, `updated_at`) не изменился;
* атомарность: payload из двух элементов (валидный `10/10` + невалидный `99999`) → **422**;
  ни первый, ни второй объект не изменились, граф показывает прежние `60/140`;
* минимумы: `width=100` → 422 `layout.size_too_small`; `height=50` → 422 `layout.size_too_small`;
  `width=20000` → 422 `layout.size_too_large`;
* типы: `width/height` для ячейки → 422 `layout.not_block`; `local_x/local_y` для блока →
  422 `layout.not_cell`;
* после всех ошибок блок остался 480×300, `updated_at` блока не изменился.

### 3.5 Автосейв: серия последовательных PUT

`test_layout_autosave_series_touches_only_sent_assets`:
* блок 640×480; 12 последовательных `PUT` (≥10 по контракту) двигают одну ячейку
  (`local_x 40…95`, `local_y 90…123`, все внутри границ);
* каждый ответ **200**, `updated=1, updated_cells=1, updated_blocks=0, skipped=[]`;
* в тесте зашиты пороги: каждый PUT < 5 с и вся серия < 30 с — фактически 12 PUT выполнились
  за 1.43 с (setup фикстур — ещё 0.20 с), т.е. ≈120 мс на запрос в in-process `TestClient`
  (JWT + проверка прав + валидация + запись в PostgreSQL); ошибок и таймаутов нет;
* цель получила последнее состояние (`95.0 / 123.0`) в БД и в графе;
* контрольные объекты (сам блок, остальные 5 ячеек и seeded `KTP-14`) — полный слепок
  (включая `version` и `updated_at`) до и после серии **идентичен**;
* размер блока после серии остался 640×480.

### 3.6 Регресс этапа 2

`test_toggle_and_cable_regression_after_stage3`:
* `POST /api/assets/{id}/toggle` on → 200, `status=on`, `previous_status=off`, `changed=true`,
  `energized=true`, `voltage_kv=6.0`, `version` вырос на 1; off → 200, `status=off`,
  `energized=false`, `voltage_kv=0.0`, в БД `status=off`;
* кабельный учёт: `POST /api/schema/assets/{id}/cables` → 201; `POST /api/cables/{id}/install` →
  200, `lifecycle_status=installed`, связь получила `cable_asset_id`, `cable_status=in_work`,
  `cable_mark`; `POST /api/cables/{id}/return {"status":"reserve"}` → 200,
  `detached_links=[id связи]`, связь очищена (`cable_asset_id/cable_mark = null`,
  `cable_status=dismounted`), но осталась живой (`deleted_at is null`, `state=connected`).

## 4. Команды и результаты

Оба прогона — на `karier_test_db` (DSN из `backend-v2/tests/.env.test`, conftest падает
до первого теста, если база не тестовая). Один pytest за раз, параллельных прогонов не было.

```
powershell -NoProfile -Command "cd C:\karier\karier\backend-v2; .\venv\Scripts\python.exe -m pytest -q tests/test_schema_interactivity.py"
→ ....... [100%]
→ 7 passed, 525 warnings in 17.75s
```

```
powershell -NoProfile -Command "cd C:\karier\karier\backend-v2; .\venv\Scripts\python.exe -m pytest -q"
→ 234 passed, 3 skipped, 650 warnings in 349.35s (0:05:49)
```

3 skipped — те же `pytest.skip`-ветки, что и в baseline 35a (227 passed, 3 skipped): новых
пропусков тесты этапа 3 не добавили. Самые долгие тесты полного прогона — прежние
(`test_blocks_s18.py`, `test_schema_blocks.py`, PDF/снимки); новый файл в топе по времени
не доминирует (`test_links_accept_ports_of_nested_cells` — 5.89 с, остальные 1.3–2.7 с).

## 5. Хеши (SHA-256)

| Файл | SHA-256 | Размер/строки |
|---|---|---|
| `backend-v2/tests/test_schema_interactivity.py` *(новый)* | `88b6ecaa74cc2d4b28426aa445016f032ce1458b74609d32e20b3674c348c54c` | 34 989 Б / 785 стр. |
| `backend-v2/app/services/gis.py` | `bba921b15aab4f59f1fcac5f8ea9acc4228ff09d375704ad9b61c405442a7e0a` | — |
| `backend-v2/app/services/schema_graph.py` | `4cd714953531d383272fbacc87d828a58dc5af8f3f64253b4514c2da5ae201c2` | — |
| `backend-v2/app/services/links.py` | `7f270c2e82beaf6a28fd4e625496fb9a6ae072cc9f1b63222a77ce0f9c2f821d` | — |
| `backend-v2/app/services/schema_blocks.py` | `40d11a3af1cd6ead2b3e369c42650b2e876660433d0724a3381f1beb055e426d` | — |
| `backend-v2/app/schemas/gis.py` | `d05e81142c626538b92af4eccf97e010fe96c28755094eb958d69adc78bb3ba6` | — |
| `backend-v2/alembic/versions/0017_schema_block_size.py` | `0f95a3d0b5a9e5c8c34633908f72da1eb895e699b09fda2f8ba7b0b273c12c71` | — |

Хеш `app/services/gis.py` совпадает с зафиксированным в отчёте db_agent
(`docs/team/35a-db-interactivity.md`, §«Хеши»): код этапа 3 между прогонами не менялся.
`package.json`/`src-v2` не менялись (этап 3 UI проверен отдельно в 35b).

## 6. Состояние тестовой БД

Снято SQL-запросом до и после прогонов:

| Метрика | До | После (individual) | После (полный) |
|---|---|---|---|
| `gis.assets` | 5049 | 5049 | 5049 |
| `gis.asset_ports` | 12965 | 12965 | 12965 |
| `gis.links` | 3788 | 3788 | 3788 |
| `gis.pits` | 1 | 1 | 1 |
| `alembic_version` | `0017_schema_block_size` | `0017_schema_block_size` | `0017_schema_block_size` |
| строки `QA3*` / `qa3-*` | 0 | 0 | 0 |

Тесты не оставляют мусора: созданные блоки/ячейки/связи удаляет `isolate_created_rows`,
«чужой карьер» — собственный `finally` в тесте. Seeded-объекты не изменяются (контроль по
`version`/`updated_at` в тесте автосейва).

## 7. Границы работы и замечания

* В зоне работы только `backend-v2/tests` и этот отчёт; `backend-v2/app`, `src-v2`,
  миграции, `package.json` не изменялись.
* Тесты используют публичные API этапа 3 (`POST /api/links`, `PUT /api/topology/layout`,
  `GET /api/topology/graph`, `GET /api/assets/{id}`) и прямые чтения БД только для проверки
  сохранённых полей/версий — то есть закрепляют контракт, а не реализацию.
* Минимальные размеры блока (120×80) и допустимые типы объектов (`layout.not_block` /
  `layout.not_cell`) проверены отдельно — при их нарушении 422 и раскладка не пишется.
* Ограничение по времени в conftest (`TEST_TIMEOUT_SECONDS=180`) не сработало ни разу:
  самый долгий тест полного прогона — 10.62 с (`test_blocks_s18.py::test_jumper_between_blocks_rejected`).
* Повторный запуск тестов идемпотентен: все создаваемые коды уникальны (`uuid4`-суффикс),
  поэтому прогон не зависит от остатков предыдущих запусков.
