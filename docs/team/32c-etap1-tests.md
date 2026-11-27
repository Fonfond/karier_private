# Этап 1 модели оборудования «Карьер»: тесты полей типа и 422 (qa_agent)

Дата: 26.11.2026 · новый файл `backend-v2/tests/test_equipment_fields.py` (10 тестов)
Прогоны: `karier_test_db` (head `0015_asset_type_fields`). Рабочая `karier_db` **не менялась**
(только read-only проверки: head `0014_schema_snapshots`, таблицы `gis.asset_type_fields` нет).

## 1. Итог

| Требование приёмки t3 | Статус | Чем подтверждено |
|---|---|---|
| Тип «отходящая ячейка» с обязательным `power_kw`: `POST /api/assets` без attrs → 422, detail по-русски, `fields` содержит обязательное поле, `field_labels` — русская подпись | ✅ | `test_outgoing_cell_without_required_field_returns_russian_422`: `fields == {"power_kw": "Обязательное поле"}`, `field_labels == {"power_kw": "Мощность"}`, `detail` = «Проверьте поля объекта: Мощность» |
| С заполненными полями → 201 | ✅ | `test_outgoing_cell_with_required_field_created`: 201, `attrs` и `cell_kind/cell_no` в ответе и в карточке |
| `GET /api/asset-types?with_fields=1`: поля отдаются с `code`/`label`/`data_type`/`required`/`unit` | ✅ | `test_asset_types_with_fields_contract`, `test_cable_type_fields_contract`, `test_created_type_fields_are_visible_with_fields` (все типы, 19 шт., + кабель и созданный тип) |
| Обратная совместимость: `POST /api/assets` со старым `attrs` и типом без полей → 201 | ✅ | `test_legacy_attrs_on_type_without_fields_still_work` (201, attrs сохранены) + `test_legacy_attr_schema_syncs_to_fields_and_still_stays_required` (старый `attr_schema` синхронизируется, 422/201 как раньше) |
| Полный `pytest -q` на `karier_test_db`: 0 failed, число passed зафиксировано, один прогон за раз | ✅ | §4.2: **214 passed, 3 skipped, 0 failed** (`289.32s`, exit 0); целевой прогон — 10 passed |
| Отчёт `docs/team/32c-etap1-tests.md`: тесты, числа, хеши `app/` и `tests/` | ✅ | этот файл, §2–§6 (манифест SHA-256: 76 файлов `app/`, 33 файла `tests/`) |

Изменены только два пути (скоуп t3): `backend-v2/tests/test_equipment_fields.py` (новый) и
`karier/docs/team/32c-etap1-tests.md` (этот отчёт). `backend-v2/app/` и `src-v2/` не трогались:
хеши ключевых файлов `app/` совпадают с отчётом `32a-db-migration.md` §6 (проверено, §6.2).

## 2. Новый файл тестов: 10 тестов

`backend-v2/tests/test_equipment_fields.py`, 19 432 байта, SHA-256
`0d05e371b90cd97d031e477d9d6092fa8f1d5d3e392eee863e57afbd5dfc2cab`.
Тесты создают собственные типы с уникальными кодами (`qa_*_<hex8>`), поэтому не зависят от
количества типов в БД; уборка созданных строк — штатная (`tests/conftest.py`,
`isolate_created_rows`). После прогона в БД не осталось ни одной строки `qa_*` (§4.3).

| № | Тест | Что закрепляет |
|---|---|---|
| 1 | `test_outgoing_cell_without_required_field_returns_russian_422` | Тип «Отходящая ячейка» (`equipment_class=cell`) с обязательным `power_kw`. POST без attrs → 422 `application/problem+json`, `code=validation.failed`; `fields` — машинный ключ + «Обязательное поле»; `field_labels` — «Мощность»; `detail` начинается с «Проверьте поля объекта» и содержит «Мощность», слова «атрибут» нет. Проверено, что подпись не подменяет машинный ключ (в `fields` нет «Мощность») |
| 2 | `test_outgoing_cell_with_required_field_created` | Тот же тип с `attrs={"power_kw": 630, "cell_no": 12}` → 201; `attrs` и `cell_kind=out`/`cell_no` в ответе; код объекта сгенерирован из кода типа; `GET /api/assets/{id}` отдаёт тот же паспорт |
| 3 | `test_field_value_checked_by_data_type_in_russian` | `power_kw: "много"` → 422 `fields={"power_kw": "Ожидается число"}`, подпись «Мощность», `detail` по-русски |
| 4 | `test_patch_asset_validates_fields` | `PATCH /api/assets/{id}` с `attrs` валидируется так же: без обязательного `power_kw` → 422; с `power_kw` → 200 и новые attrs |
| 5 | `test_asset_types_with_fields_contract` | Контракт `?with_fields=1`: набор типов тот же, что без флага; без `with_fields` `fields == []` (старый payload не вырос); у каждого поля есть `code/label/data_type/required/unit`, `data_type` из `number/integer/text/boolean/date/select`, `required` — bool, `unit` — строка/null; у каждого типа непустые `equipment_class` (из 9 классов) и `group_code`; коды полей в типе уникальны |
| 6 | `test_cable_type_fields_contract` | Тип `cable`: 5 полей; `cable_mark` («Марка кабеля», text, обязательное), `length_m` («Длина», number, «м», обязательное), `lifecycle_status` (select, options `installed/reserve/repair`, default `installed`); `equipment_class=cable`, `group_code=cables`; `GET /api/asset-types/{id}/fields` = тот же набор |
| 7 | `test_created_type_fields_are_visible_with_fields` | Поля, заданные конструктором (`fields`), видны в `?with_fields=1` в порядке `sort_order`: подписи, единица «кВт», `data_type`, `required`, `group_label` |
| 8 | `test_legacy_attr_schema_syncs_to_fields_and_still_stays_required` | Тип создан старым API (`attr_schema`/`required_attrs`, без `fields`): поля синтезируются (двойная запись 0015) с подписью «Мощность» и unit «кВт»; POST без attrs → 422 с `power_kw`, POST с прежним attrs → 201 |
| 9 | `test_legacy_attrs_on_type_without_fields_still_work` | Тип без объявленных полей (`attr_schema={}`, `required_attrs=[]`, `fields=[]`): старый клиент присылает произвольные `attrs` (`voltage_kv`, `note`, `reserve`) → **201**, attrs сохранены как есть |
| 10 | `test_cable_without_passport_returns_russian_422_and_with_passport_created` | Сценарий приёмки UI на живом типе `cable`: без паспорта → 422 `fields={cable_mark,length_m}` + русские подписи; с паспортом → 201, `lifecycle_status=installed` по умолчанию для класса `cable` |

## 3. Живой пример 422 (тот же контракт, что в тестах)

Запрос к `karier_test_db` (TestClient, токен выписан на существующего админа, данные не создавались —
валидация срабатывает до вставки):

```
GET /api/asset-types?with_fields=1 → 200
cable fields:
  cable_mark      «Марка кабеля»    text    required=True   unit=None
  length_m        «Длина»           number  required=True   unit=м
  lifecycle_status «Состояние кабеля» select required=False  unit=None
  section_mm2     «Сечение»         number  required=False  unit=мм²
  voltage_kv      «Напряжение»      number  required=False  unit=кВ

POST /api/assets {"name": "Кабель (пример для отчёта)", "type_code": "cable"} → 422
```

```json
{
  "type": "https://karier.local/errors/validation.failed",
  "title": "Проверьте поля объекта: Марка кабеля, Длина",
  "status": 422,
  "code": "validation.failed",
  "detail": "Проверьте поля объекта: Марка кабеля, Длина",
  "instance": "/api/assets",
  "request_id": "fcb3f5fe-6071-4ed0-8f88-f56afdb633dc",
  "fields": {"cable_mark": "Обязательное поле", "length_m": "Обязательное поле"},
  "field_labels": {"cable_mark": "Марка кабеля", "length_m": "Длина"}
}
```

Совпадает с примером из `32a-db-migration.md` §4.2: `fields` — машинные ключи, `field_labels` —
русские подписи, `detail` читаемый (не «Проверьте атрибуты объекта»).

## 4. Прогоны (по одному за раз, `karier_test_db`)

Порядок: сначала целевой файл, затем полный прогон (дважды подряд, §4.2); параллельных pytest не было.
Каждый прогон начинается с fail-fast проверки `tests/conftest.py`, что приложение подключено
именно к `karier_test_db` (не к `karier_db`).

### 4.1 Целевой файл

```
powershell -NoProfile -Command "cd C:\karier\karier\backend-v2; .\venv\Scripts\python.exe -m pytest -q tests/test_equipment_fields.py"
```

**10 passed**, 0 failed, 0 skipped, 6.51s, exit 0.

### 4.2 Полный прогон

```
powershell -NoProfile -Command "cd C:\karier\karier\backend-v2; .\venv\Scripts\python.exe -m pytest -q"
```

Прогон выполнен **дважды подряд** на одной и той же тестовой БД, результат совпал:

| Прогон | Итог | Время | Exit code |
|---|---|---|---|
| № 1 | **214 passed, 3 skipped, 0 failed**, 600 warnings | `289.32s (0:04:49)` | 0 |
| № 2 (повтор) | **214 passed, 3 skipped, 0 failed**, 601 warnings | `300.45s (0:05:00)` | 0 |

10 passed — новые тесты этапа 1, 204 passed — прежний регресс. Повторяемость подтверждена:
те же числа, `qa_*`-строк в БД после второго прогона тоже 0 (§4.3).

3 skipped — только `tests/test_migrations.py` (`test_single_alembic_head`,
`test_upgrade_downgrade_upgrade`, `test_autogenerate_has_only_known_drift`): не задан
`TEST_MIGRATION_DATABASE_URL`, а цикл `downgrade base` разрешён только на отдельной БД
(фикстура `migration_url` делает `pytest.skip` с явной причиной). Это не регресс: по отчёту
`32a-db-migration.md` §5 эти же тесты проходят на `karier_migrations_test` — **3 passed**.
Никаких skip в новом файле и в других тестах нет.

### 4.3 Состояние БД после прогонов

`karier_test_db`:

| Показатель | Значение |
|---|---|
| `alembic_version` | `0015_asset_type_fields` |
| типов объектов | 19 |
| полей в `gis.asset_type_fields` | 24 |
| объектов (`deleted_at is null`) | 585 |
| классов: mobile / transformer_assembly / distribution / switching / line / cable / cell | 9 / 3 / 3 / 1 / 1 / 1 / 1 |
| «мусорных» строк `qa_*` после прогона | 0 |

`karier_db` (только чтение): `alembic_version = 0014_schema_snapshots`, 36 типов,
таблицы `gis.asset_type_fields` нет — рабочая БД не менялась.

## 5. Что именно доказывает обратная совместимость

1. **Тип без полей.** `POST /api/asset-types` без `attr_schema`/`required_attrs`/`fields` даёт тип
   с `fields=[]`; `POST /api/assets` с произвольными `attrs` → 201, `attrs` возвращаются как есть
   (тест 9). Клиент, который жил на свободном JSONB, не сломан.
2. **Старый `attr_schema`/`required_attrs`.** Тип, созданный старым API, получает строки в
   `gis.asset_type_fields` (двойная запись), поэтому и новый контракт (`?with_fields=1`,
   `field_labels`) работает, и старое поведение сохраняется: без обязательного поля — 422,
   с ним — 201 (тест 8).
3. **Старый ответ `/api/asset-types`.** Без `?with_fields=1` ключ `fields` пуст — payload не вырос,
   старый фронтенд/интеграции не получают лишнего (тест 5).
4. **`attrs` не отбрасываются.** Объект можно создать с ключами, которых нет в полях типа; они
   сохраняются (тесты 9, 8). `PATCH` валидирует только присланные `attrs` (тест 4).

## 6. Хеши (SHA-256)

### 6.1 Изменённые файлы t3

| Файл (от `C:\karier\karier`) | Размер | SHA-256 |
|---|---|---|
| `backend-v2/tests/test_equipment_fields.py` (новый) | 19432 | `0d05e371b90cd97d031e477d9d6092fa8f1d5d3e392eee863e57afbd5dfc2cab` |
| `docs/team/32c-etap1-tests.md` (этот отчёт) | см. файл | хеш не фиксируется внутри себя |

### 6.2 Ключевые файлы `app/` этапа 1 — совпадают с `32a-db-migration.md` §6

| Файл (от `C:\karier\karier`) | Размер | SHA-256 | Совпадает с 32a |
|---|---|---|---|
| `backend-v2/alembic/versions/0015_asset_type_fields.py` | 24864 | `de6d362a02ca32c7e33d3ad666aa01af22637a2a495d27f12724e611ea1af624` | да |
| `backend-v2/app/services/asset_fields.py` | 31060 | `c6ebc6efec8961166c71de1ebbda706e81918e976dd8cbe1dbd6513f735b8017` | да |
| `backend-v2/app/services/gis.py` | 36526 | `8117508e9359f45b4d6085a6ba6c5892a2382abe26532e5c99d320233889351f` | да |
| `backend-v2/app/api/routers/gis.py` | 34882 | `add8b56fd0879255d5288acdab5d86356ffd7eb6d647318591a1914a26644155` | да |
| `backend-v2/app/schemas/gis.py` | 28200 | `c41063f5dd5a6afd32663915bf56afa8638129489c79ada29b811f83906c5c75` | да |
| `backend-v2/app/models/gis.py` | 16966 | `bf685d27e44562b92721abe94581e981b62b03e4b3f2882e7d4ee0bc15c02ede` | да |
| `backend-v2/app/models/__init__.py` | 1251 | `e548625e5180127d1e760dbcb41b794b1bc47e3affbc3c5ccaaf5756f61ad769` | да |
| `backend-v2/app/core/errors.py` | 2882 | `bd6191cbdf0d4b8769b99512186103ece89f89706d2c87ff0710f41c79fe9dca` | да |
| `backend-v2/app/seed_equipment_model.py` | 2939 | `644f68f02921fe5d2907cf78f8e9a9ff3d6f06f175bf6150ff8e9fb890610805` | да |

Вывод: реализация этапа 1 (db_agent) не менялась при написании тестов; qa-скоуп — только `tests/`.

### 6.3 Полный манифест `app/` и `tests/` (все `*.py`, без `__pycache__`)

76 файлов `app/` + 33 файла `tests/` = 109. Формат: `SHA-256  размер  путь`.
Пустые файлы (`__init__.py`) дают хеш `e3b0c442…b855`.

```
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/app/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/app/api/__init__.py
152f26d0511270a824ef684ca37f9bd06f75c909ddde6d743733f1e3a41068a0     3025  backend-v2/app/api/deps.py
3417177998a349e5eaeda957b629710e8d8250955171bdf13e4231204d718072     2680  backend-v2/app/api/middleware.py
415625a90a43e86307b8e93a8d251e94b044057848825d4234fcc3cc08b84013      484  backend-v2/app/api/routers/__init__.py
4f9671562ebe3c923be0fd5c6758fb91d8757829221f03c63b37feeb049e20b9     1950  backend-v2/app/api/routers/audit.py
510171040f8f15fb129e73b6f764460b090af5d111cbdf3f4199968e3bd24956     9052  backend-v2/app/api/routers/auth.py
140272a2bfbf2b03e0e6fdebaa3f2a23b289578bcefc1e1b6f59fd99d684b1ac     3689  backend-v2/app/api/routers/defects.py
ffac08b9f34e58afe72801510e34a06e9d4724c3d513a1a8234895863d9c4a37     4733  backend-v2/app/api/routers/documents.py
e98be7680bad8d67e4182122458353be34c93bdd51b0a12f04190d4a8b2a677c    14716  backend-v2/app/api/routers/employees.py
add8b56fd0879255d5288acdab5d86356ffd7eb6d647318591a1914a26644155    34882  backend-v2/app/api/routers/gis.py
6d23a1542d4278eafcc42fc1f7651fdf14e48aa9b4e5043027af27afdb7a1082      724  backend-v2/app/api/routers/health.py
d5905a0501aad04c5a80a26d8e9c7fb66f44244739e04593cb12deb98740fc34     3596  backend-v2/app/api/routers/inspections.py
1cc9b928aebcebe71cb6dabd741c16c1b70eb90a9b43b696b9eb693ae61559dc     3934  backend-v2/app/api/routers/map_layers.py
3eb3d5ceb43ca729d3d099b87fa897db1c58123dc5ccd18057885df23172a801     4592  backend-v2/app/api/routers/me.py
488b37903bf4172d9abd95e2d715eae481f8ab2708100d99b71fad037d29f806     5066  backend-v2/app/api/routers/media.py
f9ca4f5f62c5ae03ef1791a47c61a91a4c557f58875b59db3a1823be2169dc25     1506  backend-v2/app/api/routers/moves.py
390b50a6f214de10534ce4d3feb213127acffddf595e0df55d1430b0f29231aa     4549  backend-v2/app/api/routers/reports.py
1899da3b1d09ec660b27dc6f3718d5ea24fae3219b2a2ac14f51e634f8c2c7bf    12662  backend-v2/app/api/routers/schema_blocks.py
927732b472dc1ef4db2bd3011c1d8ca0e9b804d241c78570cea76e7bedc23013     2213  backend-v2/app/api/routers/sync.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/app/core/__init__.py
b8a0c70cddec255acd2d8ec562086bb5a066840e95ad6e3a567fd68ba5181adc     6402  backend-v2/app/core/config.py
bd6191cbdf0d4b8769b99512186103ece89f89706d2c87ff0710f41c79fe9dca     2882  backend-v2/app/core/errors.py
e069c17242ebf85ebf4eb9a310045781d13919d5ff165ad39e62b69735a3f26a     1054  backend-v2/app/core/ids.py
707cd77c07d824d2971a98a4b2ee1beec8b171ee739dac787c67f6a23a67787b     2807  backend-v2/app/core/rate_limit.py
cb45e764e0b03e21d1c88d1c5b604374b1461125e67485832cf3a6322c3597c2     9167  backend-v2/app/core/security.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/app/db/__init__.py
d74ad3d8af7d152357da29c5b8cc557237acb6bae26e55ee6ebd1e0bba6bab5b      782  backend-v2/app/db/session.py
5a82a8b4347e800970542bdb4da7af2b3951441930ba32aa75a694fa8568d494     8973  backend-v2/app/main.py
e548625e5180127d1e760dbcb41b794b1bc47e3affbc3c5ccaaf5756f61ad769     1251  backend-v2/app/models/__init__.py
cc4efe0ee085d9b10a1527d5a6c18ee679b0a514132f734d66337d06c667c46b     1431  backend-v2/app/models/audit.py
275c7edcf5cc25ef123bfccd437fc5fe236098d1a551485ff7923181967464eb    10037  backend-v2/app/models/auth.py
a136ac6c8715ed40d28b20374cb966edb301f26688d0cb41744d0e29ce374bd6      945  backend-v2/app/models/base.py
4730631e91905be357a9d4c77c872b5ab402f2ecaae9429d7ac148f61bd1546c     1766  backend-v2/app/models/documents.py
bf685d27e44562b92721abe94581e981b62b03e4b3f2882e7d4ee0bc15c02ede    16966  backend-v2/app/models/gis.py
3f09a332d4a594cd1a2c0c8421ccad96d8617bb2fd511aea325251833fcf208a     8221  backend-v2/app/models/ops.py
daaf3a363a31188a7deb83a1e2880427afd9367884ba70b4a651b64980c5ea6f     4419  backend-v2/app/models/sync.py
4876ae88799522f0083cb523e9770c6d458677d286ecb0ac25311142565b7098     6608  backend-v2/app/models/topology.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/app/schemas/__init__.py
31a5f5846ec433a4ed118c6353592ed80902de52c45ca03eb141a063cc76b993      759  backend-v2/app/schemas/audit.py
2604b3064cbe6bfb3f321e2d230f3b43139a99b9523bcfa30b1fd52521a6615f     3750  backend-v2/app/schemas/auth.py
d63ddd9c8506d509f950e2077e6bafd719f97432d753da4c367acd3d3c23055c      282  backend-v2/app/schemas/common.py
f4ac6103d3314ad1abc2e14984e4fb49c9c78e1b42bc0ab51eba2eca58db3762      794  backend-v2/app/schemas/documents.py
e0e6c9ae9f8f30165eb205c484776c3a97258955b8f852b0718364b1c3d82ec6     3221  backend-v2/app/schemas/employee.py
c41063f5dd5a6afd32663915bf56afa8638129489c79ada29b811f83906c5c75    28200  backend-v2/app/schemas/gis.py
c69ad0e0d012591eefca1cf92c088f56f682995e2744072f89ad381a49fe0714     4343  backend-v2/app/schemas/ops.py
5976037adc551d4f9dfc897bedf78af85e89372f771428d1b2d81c7685db9792     2592  backend-v2/app/schemas/sync.py
644f68f02921fe5d2907cf78f8e9a9ff3d6f06f175bf6150ff8e9fb890610805     2939  backend-v2/app/seed_equipment_model.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/app/services/__init__.py
dbbf3482653bfc4613f26f8591a221b5ce936e60a7feb98fd15e00aaf97a34b3     6658  backend-v2/app/services/ai_tools.py
070f63cc36130edc35fee295fe7544ba53afc5aa662d1cbf3a8b300c61013384     4745  backend-v2/app/services/analytics.py
c6ebc6efec8961166c71de1ebbda706e81918e976dd8cbe1dbd6513f735b8017    31060  backend-v2/app/services/asset_fields.py
4d2bc83ce7ab4eaff9cdc16a13270270f855dc85266c50f7f7348fa15b9c9783     4304  backend-v2/app/services/audit.py
88f884810b7c9527f50c817ece1b87de1ed4ec909e3011c0a71013ca5d4374e6    28548  backend-v2/app/services/auth.py
f82eae632493c58267e0ab35ff42543e3fd5ad275d9de343c176a096d458d099     5654  backend-v2/app/services/break_glass.py
0aecd2dd13772e8d718075f7748fa644ff65665d24390eb4043fca4c92051bf2     5687  backend-v2/app/services/composite.py
5d3caafe70ef1b943e7af29d027e76ac822c0db6c882d6af4b85f1ffb96375c7     9941  backend-v2/app/services/defects.py
0b9f1d364c1f36a7c9cce68938bd74c1c6713492e506491b0066e527da8c439b     8439  backend-v2/app/services/documents.py
8117508e9359f45b4d6085a6ba6c5892a2382abe26532e5c99d320233889351f    36526  backend-v2/app/services/gis.py
ae91f4c8121e5161085b58673c8b696cdde40a6b9d31a9911ff3c4ffd59cd776     4437  backend-v2/app/services/groups.py
de044e78424fedada19e0967b05257f416ec36287de015f24f01b34ade09ba24     7288  backend-v2/app/services/inspections.py
1fb097682bad97db880db3154ec14f38592e6c850377d8ccf6345f6afd4e2d49    11120  backend-v2/app/services/links.py
09beff856c5e9720f291acc488ea904dc83ba62cdbf37de629689b41ae85be50     2569  backend-v2/app/services/maintenance.py
cb88017967253ecebd05adb476292ff19a2e27fbb5bf8bc277d97e9ff024a5ce     6207  backend-v2/app/services/media.py
60b7e48f253fa49492a015e66c7d25e369baed0df527657a87c7a01781e13a78     3247  backend-v2/app/services/moves.py
7cda65759af075431207e0e8b8b2f2bc2912542656c74ca8cccb3c66a9826ca9     3683  backend-v2/app/services/notify.py
ab309a0e5e5cb78ec01d8b1b072599923827e9d57a2322d6005c781d1f41e1ca    11927  backend-v2/app/services/poles.py
d79b290432cea592d766f1c0c2e13bb875e299a90f60c728fa64e0be85331628    17429  backend-v2/app/services/reports.py
3b6c5778c6ccab3d3179c635bf7497103d5a7e78d429ae8850585d2c701ade1b    42053  backend-v2/app/services/schema_blocks.py
335f3863176f0e18e968839ee43aa61e49e0a1eda08ef90f09a291dbeda5523f     8845  backend-v2/app/services/schema_graph.py
06da8fe7d68268c7214607c191da8aae606b894f099203ca802b2c59336b9edc     7107  backend-v2/app/services/schema_pdf.py
a1924082578f3b0f9328cbc00467ef575439570f72b9206c25eccfb120fe3eea     5162  backend-v2/app/services/schema_snapshots.py
390a1a6f0303e9188fb4238bf799c64fa58d77b8ede61a5a058611b7dad94c34     4746  backend-v2/app/services/state.py
96ef419764765f8accd8eb9b81e2846e3fabd8845773449d37f152a5832e5d65     4287  backend-v2/app/services/storage.py
02657620d8d0ae56c4a69165d7d69892a6633b9beda7bcbd43c1ef7a12bebe64    19244  backend-v2/app/services/sync.py
f4d4d0a1af53f693fa32c51cad58ceef679c0fc48e9d1377cacd56956cb5c350    23609  backend-v2/app/services/topology.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855        0  backend-v2/tests/__init__.py
40b99ab45351011599251baa2dee6bcde37fcb47dfd1caad9c6522eb0453ccc9    13029  backend-v2/tests/conftest.py
709b7cce29a4b7da1b9e3d4e28e39bbe2ef37b9769188fe0d2e96f1c2f82a924    11354  backend-v2/tests/test_admin_api.py
b2e31727bd4266cb524aeab51a24b28779cec8051d3422675bd54b6af93bf595     3539  backend-v2/tests/test_api_contract_validation.py
5d69ab385ec71e7d248fb1e33439ad0933b5f83a31f979f0507903fad1ab5d34    13441  backend-v2/tests/test_auth_api.py
14aa5a17cbb710b0e123b45c72442c56a7a3f3f80e7918906709580fab3b5823     5725  backend-v2/tests/test_blocks_s18.py
2006c84c3124fb9480306144fb01bc53dd30f9a175ef82d1f382601154e801fb     1859  backend-v2/tests/test_blocks_s20.py
29747af232be87073db1539b4c6546159c517b059d0fd1b5c47b335310ccb31f     2929  backend-v2/tests/test_blocks_s21.py
101b68ad88c4b5abbb2959f455142ccafecfcd5abd4234ce003dec2aa53deca3     4800  backend-v2/tests/test_break_glass.py
f1656bdd109dc057e2e001ed804895b3c99a71c4d39076b74c46e986c228ee7e     3611  backend-v2/tests/test_documents_security.py
0d05e371b90cd97d031e477d9d6092fa8f1d5d3e392eee863e57afbd5dfc2cab    19432  backend-v2/tests/test_equipment_fields.py
976868d580cf59fe77f38862710e766a44af2c935a04d6041f2729256400f4f3     3917  backend-v2/tests/test_final_api.py
a0afe699c28e103df2b8c79a9b00cdbcf452770fcc370c383d1c6cc69f01e243     7864  backend-v2/tests/test_gis_api.py
da7a8bbbcfdf018240d942b152aee243c4d44a8a77efecd7062124e3446caaf8     5205  backend-v2/tests/test_gost_schema.py
0f6728e1c9400e974ec4649ae50cf27e2e18ac5a222c57be1c53e6a14b892816    10373  backend-v2/tests/test_line_builder.py
abd924ebe6942e21506b3b0792bb15d01f41a4cc05d573bb89f600b3ef420734     6274  backend-v2/tests/test_mcp_tools.py
d662572b43472064c11b1e6f4c3a7187dcd3af504c7f458b63306a7ee41525ed    14071  backend-v2/tests/test_migrations.py
720e08bcf18f471208a9ccd84509edb478b799b71fe4735bc87800455714c593     7700  backend-v2/tests/test_ops_api.py
8aa91567e32b93c80e1668a7797d541d98bd32719fe115d860f697faa53856d4     3226  backend-v2/tests/test_reports_api.py
861ab11e37fc2afeae3efdc0a56258adf85a71c9a4517be64d8c95950f5e78e4     6448  backend-v2/tests/test_schema_blocks.py
b8630c825fb174dccefd661ee8b7887978b21af32b8c73fa7e91c9076c3438cd    29467  backend-v2/tests/test_schema_builder.py
3fd5802608c37e94373d2c8d47281c30591fb9a988f0bd2266ba5c1f87ed72cb     7194  backend-v2/tests/test_schema_snapshots.py
d18d24e8e784c9a7d7c43c9f4da3705ab619dfc07ee8689195c858bf47659f9b     3766  backend-v2/tests/test_security_ip.py
92314aa9a252e52a9b19437b12cd717a2b352646dcb32cf504a7f32f945c4548     5608  backend-v2/tests/test_sketch_v2.py
3910489bc5200b3145456caa3073cc75a40df73b62b269fe33656cc412616b6a     5214  backend-v2/tests/test_sketch_v3.py
8302a1702b90b50f93c0705eae65d44c9dfee6dbba2090c5a209e5f7d17fd2c0     5168  backend-v2/tests/test_sketch_v4.py
68a10b6a6182bdd559cb8293f700448e20ce3f81fca44f3ca0bba61b90eb70a6     4286  backend-v2/tests/test_sketch_v5.py
7832cee480966963ecdc70320adda5ca736d361406fe00cadc7418dc085bc997     3724  backend-v2/tests/test_sketch_v6.py
a5d4dcd78ee051fd9de55ec05a09d41f3e528d56cb4527a63689712e6dcaa8b8     6800  backend-v2/tests/test_sprint12_api.py
023f433a93ef388777e5e0452db2b54463da6a5d11616d39cff82ab19301a984    21399  backend-v2/tests/test_sync_api.py
79f3a400c62177d148bd52f3e264a159abe9390f4d8885960a2e271383a7620b    16087  backend-v2/tests/test_topology_api.py
96eb1cb1a1961db743167e6be24e8ae821b6b5bca60c64690650c7ac59e15245     4306  backend-v2/tests/test_undo_restore.py
f4463fed7bcc70931eee2e9d49bf1a3671909469a96ce7d659f3b8bfa5614a05     7400  backend-v2/tests/test_ux_api.py
```

## 7. Замечания и границы

1. **`tests/test_assets_api.py` из контракта t1 не существует.** Целевая verify-команда этапа 1
   теперь ссылается на реальный файл `tests/test_equipment_fields.py` и проходит дословно.
2. **3 skipped — не регресс.** Это `test_migrations.py`, которым нужна отдельная БД
   (`TEST_MIGRATION_DATABASE_URL`, как `karier_migrations_test`); без неё фикстура делает
   осознанный skip. По `32a` они проходят: 3 passed. Полный прогон с переменной — задача
   приёмки этапа 1 (t4), здесь важно, что **0 failed**.
3. **UI-тесты этапа 1** (`vitest`: 48 passed, `typecheck`/`build` exit 0) — зона `ui_agent` (t2),
   в этот отчёт не входят: t3 — backend-тесты и полный регресс.
4. **Ячейки-шаблоны, кнопки включения/отключения и цвета** — этап 2; здесь не тестировались
   (в этапе 1 есть только колонки `cell_kind/cell_no/section_no` и `lifecycle_status`).
5. **Рабочая БД.** Все проверки `karier_db` — только `SELECT` (head 0014, 36 типов, таблицы
   `gis.asset_type_fields` нет). Миграция на рабочую БД не запускалась.
6. **Повторяемость.** Тесты не зависят от порядка запуска (уникальные коды, штатная уборка).
   Полный прогон дважды подряд на одной БД дал те же **214 passed / 3 skipped / 0 failed**
   (§4.2), «мусорных» строк `qa_*` после второго прогона — 0: снимок PK в
   `isolate_created_rows` удаляет ровно созданное тестом.
