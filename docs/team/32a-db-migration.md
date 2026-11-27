# Этап 1 модели оборудования «Карьер»: БД и API (db_agent)

Дата: 26.11.2026 · миграция `0015_asset_type_fields` · проверено на `karier_test_db`
Рабочая БД `karier_db` **не менялась** (осталась на `0014_schema_snapshots`, новых колонок нет).

## 1. Итог

| Требование этапа 1 | Статус | Чем подтверждено |
|---|---|---|
Миграция 0015 up→down→up, head = 0015, данные не теряются | ✅ | §3: цикл на `karier_test_db`, счётчики и md5 до/после совпали |
`gis.asset_type_fields` создана и заполнена из `attr_schema`/`required_attrs` | ✅ | 24 поля у 19 типов (в т.ч. 5 у нового `cable`); §2.1 |
`attr_schema`/`required_attrs` сохранены (обратная совместимость) | ✅ | md5 `attr_schema` существующих типов не изменился; §2.2 |
`equipment_class` у всех активных типов по карте + `group_code` | ✅ | §2.3: 0 типов без класса, 7 непустых групп |
Тип `cable` + CHECK `lifecycle_status in (installed,reserve,repair)` | ✅ | §2.4: тип создан, 5 полей, CHECK на `gis.assets` |
`gis.assets.cell_kind/cell_no/section_no` без потери данных | ✅ | §2.5: 2250 ячеек размечено, 454 номера, 0 секций (в данных нет секций) |
`GET /api/asset-types?with_fields=1` отдаёт поля типа | ✅ | §4.1 (живой вызов на тестовой БД) |
`POST /api/assets` валидирует поля, 422 с `fields` + русские `field_labels` | ✅ | §4.2 (пример ответа) |
Старые вызовы `POST /api/assets` с `attrs` работают | ✅ | §4.3 + `test_gis_api.py::test_required_attrs_validated` |
Регресс-поднабор pytest зелёный | ✅ | §5: 19 + 61 + 30 passed, `test_migrations` 3 passed (полный прогон — за qa_agent) |

## 2. Миграция 0015 (`backend-v2/alembic/versions/0015_asset_type_fields.py`)

Только additive: ни одна таблица/колонка/строка не удаляется. Порядок: схема → разметка
классов → тип `cable` → поля из `attr_schema` → перенос ячеек/кабеля из JSONB.

### 2.1 `gis.asset_type_fields` — поля паспорта типа

```
id uuid pk, asset_type_id uuid → gis.asset_types(id) on delete cascade,
code text, label text, unit text,
data_type text check (number|integer|text|boolean|date|select),
required bool default false, default_value jsonb, options jsonb,
min numeric(14,4), max numeric(14,4), group_label text, sort_order int,
unique(asset_type_id, code), index(asset_type_id, sort_order)
```

Мигратор: для каждого типа из `attr_schema` берётся правило поля (`type` → `data_type`,
`options`, `default`, `min`/`max`, `label`/`unit`/`group_label`, если заданы), из
`required_attrs` — признак обязательности. Порядок детерминированный: обязательные поля
первыми, дальше по алфавиту, `sort_order` = 10, 20, 30… Подписи и единицы известных
полей — из словаря `FIELD_META` (`power_kw` → «Мощность, кВт» и т.д.), он же используется
API, чтобы 422 были по-русски. Неизвестный код получает подпись из кода
(`serial_no` → «Serial no») до момента, когда админ задаст свою.

Заполнено на тестовой БД: **24 поля у 19 типов**, например `ktp`:
`power_kva` («Полная мощность», кВ·А), `voltage_in_kv` («Напряжение на входе», кВ),
`voltage_out_kv` («Напряжение на выходе», кВ); `dmo`: `power_kw` (обязательное),
`drive_type`. У типов без `attr_schema` (`substation`, `bkru`, `cell`, `pole`…) полей нет —
это ожидаемо: форма покажет только паспортные поля, которые админ задал в типе.

### 2.2 Обратная совместимость (двойная запись)

`asset_types.attr_schema` и `asset_types.required_attrs` **не удалены и не переписаны**
миграцией. Синхронизация в обе стороны живёт в `app/services/asset_fields.py`:

* `sync_from_schema()` — тип правили старым API (`attr_schema`/`required_attrs`) → таблица
  полей догоняет (лишние коды не удаляются);
* `replace_fields()` — админ прислал `fields` → из них пересобираются `attr_schema`/
  `required_attrs` (старый клиент увидит привычный JSON-Schema);
* `public_fields()` — если таблица полей почему-то пуста (перезалив демо-дампа), API
  отдаёт поля, выведенные из `attr_schema` «на чтение», а не пустую форму.

### 2.3 Классы оборудования (`asset_types.equipment_class`, `group_code`)

`equipment_class text not null default 'equipment'` + CHECK по списку
`distribution | transformer_assembly | switching | cell | cable | mobile | line | source | equipment`.
`group_code` — код вкладки UI (этап 2).

| Класс | `group_code` (вкладка) | Типы в `karier_db` | Типы в `karier_test_db` |
|---|---|---|---|
`distribution` | `distribution` | `ps_35`, `bkru_1`, `bkru_2` | `substation`, `bkru`, `bus_section` |
`transformer_assembly` | `transformers` | `ktp`, `yaku_1t`, `ksr` | `ktp`, `ksr`, `yaku_1t` |
`switching` | `switching` | `yakno_vozduh_kabel`, `yakno_vozduh_vozduh`, `yaku`, `yaku_vozduh_vozduh` | `yaku` |
`cell` | `cells` | `yacheyka_2`, `yacheyka_3`, `yacheyka_bkru_2` | `cell` |
`cable` | `cables` | новый `cable` | новый `cable` |
`mobile` | `mobile` | `generator_benzinovyy`, `generator_dizelnyy`, `dmo_dizelnaya_machta_osvescheniya`, `mo_machta_osvescheniya`, `motopompa_dizelnaya` | `dmo`, `dmp`, `bmp`, `gen_diesel`, `gen_petrol`, `cuckoo`, `mast`, `ekg`, `pump` |
`line` | `lines` | `op` | `pole` |
`source` | `sources` | `source_35` (если появится) | — |
`equipment` (Прочее) | `other` | запасной вариант для будущих типов | запасной вариант |

Правила для типов вне карты (порядок): код из явной карты → префикс/название
(`yach_*`/«ячейка» → cell, «опора»/`op` → line, «кабель» → cable, `ps_*`/«подстанция»/
«БКРУ» → distribution, `ktp`/`кср`/«трансформатор» → transformer_assembly, `yakno`/`yaku`/
«ЯКНО»/«ЯКУ» → switching, «генератор»/«ДГУ»/«ДМО»/«ДМП»/«БМП»/«мачта»/«насос»/
«экскаватор»/«кукушка» → mobile) → старая `category` (`source→source`, `line/pole→line`,
`mobile/lighting/aux→mobile`, `equipment→switching`). Значение `equipment` («Прочее»)
оставлено допустимым CHECK-ом, чтобы тип, созданный через админку, не падал 500/422 до
того, как администратор выбрал класс; API при этом отдаёт вычисленный класс
(`effective_class()`), а не «Прочее», если класс выводится однозначно.

В тестовой БД после миграции: `0` типов без класса, распределение
`mobile 9, distribution 3, transformer_assembly 3, cable 1, cell 1, switching 1, line 1`.
В рабочей БД (36 типов, в т.ч. архивные) размечены все, включая неактивные.

Карта проверена **на реальных данных рабочей БД без записи** (read-only dry-run
`infer_equipment_class` по 36 типам `karier_db`): все 36 попадают в 8 утверждённых классов,
`equipment`/«Прочее» — ни одного, у всех 19 активных типов класс определён:
`distribution 7 (ps_35, bkru_1, bkru_2, tps…), mobile 5, transformer_assembly 3 (ktp, ksr, yaku_1t),`
`switching 5 (yakno_*, yaku, yaku_vozduh_vozduh), cell 15 (yacheyka_*, yach_*), line 1 (op)`.
Миграция на рабочей БД не запускалась (запрет задачи) — при раскатке она разметит те же 36 типов.

### 2.4 Кабель: отдельная колонка `lifecycle_status` (решение и обоснование)

Выбрана **отдельная колонка** `gis.assets.lifecycle_status text null` +
`CHECK (lifecycle_status in ('installed','reserve','repair'))`, а не CHECK по JSONB `attrs`:

1. **Проверка БД, а не приложения.** CHECK на `attrs` в PostgreSQL фактически не
   выражается без триггера: `attrs` — произвольный JSON, ограничение вида
   `attrs->>'lifecycle_status' in (...)` пропустит `NULL` и любой другой мусор в attrs.
   Колонка с CHECK гарантирует корректность на уровне схемы.
2. **Типизация и индекс.** По колонке можно строить индекс/фильтр «в запасе» без
   `GIN`/expression-index, значения не зависят от регистра/написания ключа в JSON.
3. **Не смешивается с `lifecycle`.** У объекта уже есть `lifecycle`
   (`planned|installed|reserve|written_off`) — это жизненный цикл объекта (списан/план),
   а `lifecycle_status` — состояние кабеля как изделия (на оборудовании / в запасе /
   в ремонте). Разные смыслы — разные колонки.
4. **Совместимость.** Старый `links.cable_status` и `attrs.reserve` остаются; мигратор
   переносит `attrs.reserve=true` → `lifecycle_status='reserve'` (в тестовой БД 133
   строки), значение из `attrs.lifecycle_status` переносится, кабелям без значения
   ставится `installed`.

Тип `cable` («Кабель», category `line`, `equipment_class='cable'`, `group_code='cables'`,
sort 120, порты «Начало/Конец») создаётся миграцией, если его ещё нет; существующий только
размечается. Его поля в `gis.asset_type_fields`:

| code | label | unit | data_type | required |
|---|---|---|---|---|
`cable_mark` | Марка кабеля | — | text | да |
`length_m` | Длина | м | number | да |
`lifecycle_status` | Состояние кабеля | — | select `installed/reserve/repair`, default `installed` | нет |
`section_mm2` | Сечение | мм² | number | нет |
`voltage_kv` | Напряжение | кВ | number | нет |

`attr_schema`/`required_attrs` типа `cable` заполнены тем же составом (двойная запись).

### 2.5 Ячейки ПС/БКРУ (`cell_kind`, `cell_no`, `section_no`)

* `cell_kind text null`: CHECK `in ('in','out','sectional')` (по заданию этапа);
* `cell_no int null`, `section_no int null`;
* перенос из существующих данных: `schema_role`: `incoming→in`, `outgoing→out`,
  `section→sectional`; `attrs.cell` («Яч. 3») → `cell_no=3`; `attrs.cell_no`/`attrs.section_no`/
  `attrs.section` → соответствующие колонки. Переносятся только NULL-значения (идемпотентно).
* в тестовой БД размечено **2250 ячеек** (654 вводных, 1282 отходящих, 314 секционных),
  **454** номера ячеек; `section_no` — 0, потому что в загруженных демо-данных секций в
  attrs нет. `schema_role` и `attrs` не тронуты — обратная совместимость схемы и отчётов.

### 2.6 Откат (downgrade)

Удаляются только новые колонки/таблица и CHECK-и; тип `cable` удаляется, только если на
него ещё не ссылаются объекты (иначе остаётся — данные важнее симметрии). `attr_schema`,
`required_attrs`, `attrs`, `schema_role` не менялись, поэтому после повторного
`upgrade` поля/классы/номера восстанавливаются из них. Проверено циклом up→down→up: md5
`attr_schema` существующих типов и md5 `attrs` всех объектов **до и после совпали**
(`7e0e0f36…` и `29f02bcc…`), количество объектов/портов/связей не изменилось.

## 3. Проверка миграции на `karier_test_db` (рабочая БД не тронута)

Перед прогоном DSN подменяется переменной окружения (иначе `alembic` возьмёт `karier_db`
из `backend-v2/.env` — этого делать нельзя):

```powershell
cd C:\karier\karier\backend-v2
$env:DATABASE_URL = "postgresql+psycopg://karier_user:<пароль>@127.0.0.1:5432/karier_test_db"
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m alembic downgrade -1
.\venv\Scripts\python.exe -m alembic upgrade head
```

| Что | До | После |
|---|---|---|
Ревизия | `0014_schema_snapshots` | `0015_asset_type_fields` (head) |
Типы / объекты / порты / связи | 18 / 4790 / 12330 / 3866 | 19 (+`cable`) / 4790 / 12330 / 3866 |
`gis.asset_type_fields` | нет | 24 строки |
md5 `attr_schema`+`required_attrs` существующих типов | `7e0e0f36d82b2da04b762f68f5f4acce` | тот же |
md5 `attrs` всех объектов | `29f02bcc11ed3e6dc944909255bc82e0` | тот же |
`cell_kind` | нет колонки | 654 in / 1282 out / 314 sectional / 2540 NULL |
`cell_no` | нет колонки | 454 |
`lifecycle_status` | нет колонки | 133 `reserve`, 4657 NULL |
Рабочая `karier_db` | 0014 | 0014 (не менялась) |

Дополнительно `compare_metadata` (autogenerate) на тестовой БД после миграции даёт ровно
**29** известных baseline-расхождений из `tests/test_migrations.py` — новых расхождений
моделей и БД нет.

Полный цикл **с пустой БД** проверен отдельно (временная `karier_migrations_test`, после
проверки удалена; рабочая и тестовая БД не затрагивались):

```powershell
$env:TEST_MIGRATION_DATABASE_URL = "postgresql+psycopg://karier_user:<пароль>@127.0.0.1:5432/karier_migrations_test"
.\venv\Scripts\python.exe -m pytest -q tests/test_migrations.py
# 3 passed: одна голова (0015), upgrade head → downgrade base → upgrade head,
# autogenerate = только известный baseline-дрейф (29 операций)
```

### 3.1 Важно: перезалив демо-данных в тестовую БД

`.local/reset-test-db.ps1` собирает тестовую БД так: миграции на пустой схеме → TRUNCATE →
загрузка демо-дампа (`backups/karier_before_clean_20261109.dump`, схема 0013/0014). В этом
сценарии строки типов появляются **после** мигратора, поэтому `equipment_class` получает
server_default `equipment`, полей и типа `cable` нет. Для этого добавлен идемпотентный
модуль (в скоупе `app/`):

```powershell
cd C:\karier\karier\backend-v2
$env:DATABASE_URL = "postgresql+psycopg://karier_user:<пароль>@127.0.0.1:5432/karier_test_db"
.\venv\Scripts\python.exe -m app.seed_equipment_model
```

Он добирает классы/вкладки, тип `cable`, поля из `attr_schema` и колонки ячеек/кабеля;
повторный запуск — no-op (проверено: первый проход после «потери» данных вернул 18 классов,
18 вкладок, 19 полей, 2250 `cell_kind`, 454 `cell_no`, 133 кабельных статуса; второй — 0).
Если QA будет пересобирать тестовую БД, этот модуль нужно вызывать после загрузки дампа
(изменение самого `.local/reset-test-db.ps1` — вне моего скоупа; рекомендую капитанy
добавить туда одну строку). Даже без запуска API не отдаёт пустую форму: `with_fields=1`
и классы вычисляются из `attr_schema`/кода «на чтение» (см. §2.2).

## 4. API-контракт

### 4.1 `GET /api/asset-types?with_fields=1`

Поля добавлены в существующий ответ `AssetTypeOut` (additive): у типа появились
`equipment_class`, `group_code`, `fields`. Без `with_fields` (и в старом клиенте)
`fields` — пустой список, остальные ключи не менялись.

```json
{
  "id": "…", "code": "ktp", "name": "КТП (комплектная трансформаторная подстанция)",
  "category": "equipment",
  "equipment_class": "transformer_assembly",
  "group_code": "transformers",
  "attr_schema": {"power_kva": {"type": "number"}, "voltage_in_kv": {"type": "number"}, "voltage_out_kv": {"type": "number"}},
  "required_attrs": [],
  "fields": [
    {"id": "…", "code": "power_kva", "label": "Полная мощность", "unit": "кВ·А", "data_type": "number",
     "required": false, "default_value": null, "options": [], "min": null, "max": null,
     "group_label": "Мощность", "sort_order": 10},
    {"id": "…", "code": "voltage_in_kv", "label": "Напряжение на входе", "unit": "кВ", "data_type": "number",
     "required": false, "options": [], "group_label": "Напряжение", "sort_order": 20}
  ]
}
```

Дополнительно: `GET /api/asset-types/{type_id}/fields` → `list[AssetTypeFieldOut]`
(то же, что `fields`). `POST`/`PATCH /api/asset-types` теперь тоже отвечают с `fields`
и принимают `equipment_class`, `group_code`, `fields` (конструктор админа; без него
работает старое тело с `attr_schema`/`required_attrs`).

### 4.2 `POST /api/assets`: 422 по полям типа, по-русски

Валидация идёт по `gis.asset_type_fields` (обязательность, типы, `select`-опции, `min`/`max`);
если у типа полей нет — работает прежняя проверка по `attr_schema`/`required_attrs`.
Ошибка — тот же problem+json, что и раньше, плюс `field_labels` рядом с машинными ключами
(`fields` не подменяются подписями — контракт `test_api_contract_validation.py` сохранён):

```json
{
  "type": "https://karier.local/errors/validation.failed",
  "title": "Проверьте поля объекта: Марка кабеля, Длина",
  "status": 422,
  "code": "validation.failed",
  "detail": "Проверьте поля объекта: Марка кабеля, Длина",
  "fields": {"cable_mark": "Обязательное поле", "length_m": "Обязательное поле"},
  "field_labels": {"cable_mark": "Марка кабеля", "length_m": "Длина"}
}
```

Сообщения: «Обязательное поле», «Ожидается число», «Ожидается целое число», «Ожидается
да/нет», «Ожидается дата в формате ГГГГ-ММ-ДД», «Недопустимое значение (допустимо: …)»,
«Значение меньше минимального (N)», «Значение больше максимального (N)». В `detail`
подписи свёрнуты: до 4 полей перечислены, дальше «и ещё N».

`PATCH /api/assets` с `attrs` валидирует так же (`check_required=False` для ячеек схемы —
поведение Спринта 21 сохранено).

### 4.3 Новые поля объекта (additive)

`POST/PATCH /api/assets` принимают `cell_kind` (`in|out|sectional`), `cell_no`,
`section_no`, `lifecycle_status` (`installed|reserve|repair`); `AssetOut`/`AssetBriefOut`
их отдают (nullable). Для объекта типа класса `cable` без явного значения
`lifecycle_status` проставляется `installed`. Старые вызовы без этих полей работают
(все они nullable); `attrs` по-прежнему принимается как есть, лишние ключи не отбрасываются.

## 5. Регресс (на `karier_test_db`, вручную; полный прогон — qa_agent)

| Команда | Результат |
|---|---|
`pytest -q tests/test_gis_api.py tests/test_sprint12_api.py tests/test_api_contract_validation.py` | **19 passed** (включая `test_required_attrs_validated`, контракт `fields`/`field_labels`) |
`pytest -q tests/test_admin_api.py tests/test_schema_builder.py tests/test_topology_api.py tests/test_ux_api.py tests/test_final_api.py tests/test_schema_blocks.py tests/test_blocks_s18.py` | **61 passed** (в т.ч. `test_bulk_cells_skip_required_attrs_of_cell_type`) |
`pytest -q tests/test_gis_api.py tests/test_sprint12_api.py tests/test_api_contract_validation.py tests/test_admin_api.py` (после финальных правок) | **30 passed** |
`pytest -q tests/test_migrations.py` на временной `karier_migrations_test` (`TEST_MIGRATION_DATABASE_URL`) | **3 passed** — одна голова, полный цикл base→head→base→head, autogenerate = baseline
`python -c "from app.main import app; print(sorted(... 'asset-types' or 'cables' ...))"` | `/api/asset-types`, `/api/asset-types/{type_id}`, `/api/asset-types/{type_id}/fields`, `/api/schema/assets/{asset_id}/cables` |

Замечание: в контракте задачи вторая команда verify ссылается на `tests/test_assets_api.py`,
но такого файла в репозитории нет (тесты этапа 1 пишет qa_agent в `tests/test_equipment_fields.py`).
Дословная команда падает **до сбора тестов** (`ERROR: file or directory not found`), поэтому
регресс прогнан по фактически существующим файлам выше. Как только qa добавит файл, поднабор
из контракта можно запускать дословно.

Ручные API-проверки (TestClient поверх `karier_test_db`, созданные объекты удалены):
`GET with_fields=1` → 200 с полями `ktp`/`dmo`/`cable`; `POST dmo` без `attrs` → 422
`{"power_kw": "Обязательное поле"}` + `field_labels={"power_kw": "Мощность"}`; `POST dmo`
с `power_kw: "много"` → 422 «Ожидается число»; `POST cable` без полей → 422 с двумя
обязательными; `POST cable` с `lifecycle_status: "bogus"` → 422 «Недопустимое значение»;
`POST cable/dmo/ktp` с корректными `attrs` (и старым `attrs={"power_kva": 100}`) → 201;
`POST cell` с `cell_kind/cell_no/section_no` → 201 и значения в ответе; `PATCH cable` без
`length_m` → 422. Создание типа через `fields` и правка `attr_schema`↔`fields` — 201/200,
обе стороны двойной записи сходятся.

## 6. Файлы и хеши (SHA-256)

| Файл (от `C:\karier\karier`) | Размер | SHA-256 |
|---|---|---|
`backend-v2/alembic/versions/0015_asset_type_fields.py` | 24864 | `de6d362a02ca32c7e33d3ad666aa01af22637a2a495d27f12724e611ea1af624` |
`backend-v2/app/services/asset_fields.py` (новый) | 31060 | `c6ebc6efec8961166c71de1ebbda706e81918e976dd8cbe1dbd6513f735b8017` |
`backend-v2/app/services/gis.py` | 36526 | `8117508e9359f45b4d6085a6ba6c5892a2382abe26532e5c99d320233889351f` |
`backend-v2/app/api/routers/gis.py` | 34882 | `add8b56fd0879255d5288acdab5d86356ffd7eb6d647318591a1914a26644155` |
`backend-v2/app/schemas/gis.py` | 28200 | `c41063f5dd5a6afd32663915bf56afa8638129489c79ada29b811f83906c5c75` |
`backend-v2/app/models/gis.py` | 16966 | `bf685d27e44562b92721abe94581e981b62b03e4b3f2882e7d4ee0bc15c02ede` |
`backend-v2/app/models/__init__.py` | 1251 | `e548625e5180127d1e760dbcb41b794b1bc47e3affbc3c5ccaaf5756f61ad769` |
`backend-v2/app/core/errors.py` | 2882 | `bd6191cbdf0d4b8769b99512186103ece89f89706d2c87ff0710f41c79fe9dca` |
`backend-v2/app/seed_equipment_model.py` (новый) | 2939 | `644f68f02921fe5d2907cf78f8e9a9ff3d6f06f175bf6150ff8e9fb890610805` |

Не менялись: `tests/`, `src-v2/`, `backend-v2/.env`, `backend-v2/alembic.ini`,
`seed_gis.py` (тип `cable` добавляет миграция, а не сид). Рабочая `karier_db` — на 0014.

## 7. Что осталось на этап 2 (после отчёта)

1. **Status API** включения/отключения: `POST /api/assets/{id}/state` уже есть (Спринт 4),
   но в этап 2 нужны: `GET /api/cables?scope=installed|reserve`, `POST /api/cables`,
   `POST /api/assets/{id}/install|return` (установить/снять кабель), цвета статусов в UI.
   В этап 1 сделана только колонка `lifecycle_status` и тип `cable` — маршрутов `/api/cables`
   сознательно нет (это этап 2/4 плана 31), поэтому в списке маршрутов их не видно.
2. **Ячейки-шаблоны**: `composite_template` v2 (секции/вводные/секционные/отходящие),
   `POST /api/assets/{id}/compose`, предпросмотр и создание ПС 17/секция и БКРУ-6 одним
   вызовом; `POST /api/assets/{id}/cells/bulk` расширить `cell_kind`/`cell_no`/`section_no`.
3. **Классы в UI**: `GET /api/equipment/classes` (счётчики по классам) — не делал, вкладки
   этапа 2 могут строиться по `group_code` из `with_fields=1`.
4. **Админ-конструктор полей**: `POST/PATCH/DELETE /api/asset-types/{id}/fields` — сервис
   (`replace_fields`) уже готов, нужны маршруты и UI.
5. **Паспортные поля** (`serial_no`, `manufacturer`, `model`, `commissioned_on`,
   `warranty_until`) и миграция 0016 с `location_kind` — следующий этап (в 0015 не добавлял,
   чтобы не расширять скоуп).
6. **Индексы** `assets(asset_type_id)`, `assets(location_kind)`, `links(cable_asset_id)` —
   вместе с 0016.
7. Тесты этапа 1 (`tests/test_equipment_fields.py`) и полная приёмка — qa_agent (t3/t4).
