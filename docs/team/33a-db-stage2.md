# Этап 2 модели оборудования «Карьер»: БД и API (db_agent)

Дата: 26.11.2026 · миграция `0016_stage2_equipment` · проверено на `karier_test_db`
Рабочая БД `karier_db` **не менялась** (read-only проверка: head `0015_asset_type_fields`,
колонки `gis.links.cable_asset_id` нет, типа `razedinitel` нет).

## 1. Итог

| Требование этапа 2 (контракт t1) | Статус | Чем подтверждено |
|---|---|---|
| Миграция 0016 additive: `gis.links.cable_asset_id` (FK `gis.assets`, nullable, индекс) + `asset_types.composite_template` v2 + seed шаблонов БКРУ/ПС 35/6 | ✅ | §2, §3: up→down→up на `karier_test_db`, md5 данных до/после совпали |
| `POST /api/schema/composite` (admin) БКРУ → ровно 6 ячеек: `in, out, out, sectional, out, in`, номера 1…6, `section_no` 1,1,1,1,2,2 | ✅ | §5.1 (живой вызов), §4.1 |
| ПС 35/6 → по 17 ячеек на секцию (15 `out` + 1 `in` + 1 `sectional`), `cells_per_section` 1…50 меняет число отходящих, ответ содержит блок/ячейки/секции | ✅ | §5.2, §5.3: 34 ячейки (17+17), `cells_per_section=10` → 10+10; вне 1…50 → 422 |
| КТП → 0 ячеек, но вводной разъединитель (дочерний объект класса `switching`, `cell_kind=in`), его `id` в ответе | ✅ | §5.4: `children=1`, `cells=[]`, `disconnector.id` (тип `razedinitel`) |
| `POST /api/assets/{id}/toggle` (право `asset.status.edit`): on/off, ответ `{status, energized, voltage_kv, grounded}`, аудит с актором и прежним/новым состоянием, без права 403 | ✅ | §5.5, §5.7; audit-строка `asset.toggled` с `from_state`→`to_state` |
| Кабели: `GET /api/cables?lifecycle_status=`, `POST /api/cables/{asset_id}/install` и `/return` меняют installed/reserve/repair, установка на линию заполняет `links.cable_asset_id`, аудит, невалидный статус → 422 | ✅ | §5.6: install по `link_id` → `links.cable_asset_id`, `/return` → `reserve`/`repair`, `?lifecycle_status=bogus` → 422 |
| Старые API не сломаны, attr-поля/шаблоны блоков работают | ✅ | §6: 24 + 82 passed; `/api/composites/place` по БКРУ → 6 ячеек; `with_fields=1` работает |
| Отчёт с контрактами, хешами, миграцией | ✅ | этот документ (§2–§9) |

## 2. Миграция `0016_stage2_equipment`

Файл: `backend-v2/alembic/versions/0016_stage2_equipment.py`, `down_revision = 0015_asset_type_fields`.
Только additive: новые колонка/индекс/FK/тип/данные; ни одна таблица, колонка или строка не удаляется.
В `downgrade` снимается только добавленное миграцией и восстанавливаются шаблоны, если их не правил админ.

### 2.1 `gis.links.cable_asset_id` — кабель-объект на участке связи

```
cable_asset_id uuid NULL
  FK fk_links_cable_asset_assets → gis.assets(id) ON DELETE SET NULL
  INDEX ix_links_cable_asset (cable_asset_id)
```

* **nullable + SET NULL**: удалили/архивировали кабель — связь остаётся живой, «просто без кабеля»;
  каскад здесь был бы опасен (пропала бы электрическая связь вместе с карточкой кабеля).
* **Индекс** — фильтр «где установлен кабель» без seq scan (в тестовой БД 3788 связей).
* Старые денормализованные поля `cable_mark`, `cable_no`, `cable_status`, `installed_on`,
  `length_m`, `cross_section_mm2` **не удалены** и заполняются из карточки кабеля при установке:
  отчёты и старый клиент работают как раньше.

### 2.2 `asset_types.composite_template` v2 — формат

Колонка существует с 0013; миграция меняет только **значение** у профилей БКРУ/ПС/КТП.
Формат v2 — по-прежнему **JSON-массив** (не объект!):

```json
[
  {"version": 2, "profile": "bkru", "title": "БКРУ (6 ячеек)", "configurable": false, "cells": 6},
  {"version": 2, "section_no": 1, "label": "Секция 1", "voltage_kv": 6.0,
   "cells": [{"cell_kind": "in", "count": 1, "label": "Вводная", "voltage_kv": 6.0},
             {"cell_kind": "out", "count": 2, "label": "Отходящая", "voltage_kv": 6.0},
             {"cell_kind": "sectional", "count": 1, "label": "Секционная", "voltage_kv": 6.0}]},
  {"version": 2, "section_no": 2, "label": "Секция 2", "voltage_kv": 6.0,
   "cells": [{"cell_kind": "out", "count": 1, "label": "Отходящая", "voltage_kv": 6.0},
             {"cell_kind": "in", "count": 1, "label": "Вводная", "voltage_kv": 6.0}]}
]
```

Почему список, а не объект из плана 31 §3.5 (`{"sections": …, "cells": …}`): старый админ-клиент
(`src-v2/src/pages/TypesPage.tsx`) делает `(type.composite_template ?? []).map(...)`. Объект сломал бы
`GET /api/asset-types` в старом UI (`.map is not a function`). Поэтому v2 — массив: первый элемент
метаданные (версия, профиль, настраиваемость, `cells_per_section`), дальше по элементу на секцию с
**упорядоченным** списком ячеек. Код этапа 2 (и обновлённый UI) читает эту структуру; старый код
видит массив и не падает. Разбор обоих форматов (v2-массив, dict плана 31, legacy v1) —
`app/services/equipment_templates.py::parse_template`.

Заполнено миграцией (по коду/названию типа, копия карты — `equipment_templates.profile_for_type`):

| Профиль | Коды/признаки | Шаблон |
|---|---|---|
| `bkru` | `bkru`, `bkru_1`, `bkru_2`, в названии «БКРУ» | 6 ячеек: секция 1 — `in, out×2, sectional`; секция 2 — `out, in` |
| `ps_35_6` | `ps_35`, `ps_35_6_kv`, `ps_35_6_kv_2`, `substation`, `tps`, в названии «ПС …»/«подстанция» | 2 секции × (`in` + `out*` + `sectional`), по умолчанию 17 на секцию (`cells_per_section: 17`), секция 1 — 35 кВ, секция 2 — 6 кВ |
| `ktp` | `ktp`, «КТП» в названии | 0 ячеек + вводной разъединитель (`{"cell_kind":"in","type_code":"razedinitel","voltage_kv":6.0}`) |

Порядок проверки: БКРУ → КТП → ПС (иначе «КТП (комплектная трансформаторная **подстанция**)»
попал бы в ПС). Типы, не попавшие в профили (ЯКНО/ЯКУ/КСР и их старые v1-шаблоны Спринта 21),
**не трогаются**. КТП-профиль намеренно заменяет старый v1-шаблон `ktp` (5 случайных объектов):
по заданию этапа КТП — без ячеек, только вводной разъединитель.

### 2.3 Тип `razedinitel` — «Разъединитель» для КТП

Если в справочнике нет `razedinitel`, миграция создаёт тип: `category=equipment`,
`equipment_class=switching`, `group_code=switching`, `schema_symbol=disconnector`,
sort 190, порты `IN-1`/`OUT-1` 6 кВ, поля `voltage_kv` (кВ) и `drive_type` в `gis.asset_type_fields`.
Если тип уже есть — только `is_active=true`. Тот же код идемпотентно добирает
`python -m app.seed_equipment_model` (для тестовой БД, собранной перезаливом демо-дампа после миграций).

### 2.4 Откат (downgrade)

1. Шаблоны профилей, которые всё ещё **побайтово совпадают с сидовыми**, сбрасываются в `[]`,
   `is_composite=false`. Если админ отредактировал состав — шаблон остаётся (правки не теряются).
2. Тип `razedinitel` удаляется, только если на него не ссылаются объекты.
3. Удаляются индекс `ix_links_cable_asset`, FK `fk_links_cable_asset_assets` и колонка
   `links.cable_asset_id`.

Ограничение: исходное v1-содержимое `composite_template` у `bkru_1/bkru_2/ps_35/ktp` в рабочей БД
перезаписывается на v2 (это требование этапа), откат возвращает `[]`, а не прежний v1. В тестовой
БД таких v1-шаблонов у профилей не было (§3).

## 3. Проверка миграции на `karier_test_db` (рабочая БД не тронута)

DSN подменяется переменной окружения — иначе `alembic` возьмёт `karier_db` из `backend-v2/.env`
(этого делать нельзя):

```powershell
cd C:\karier\karier\backend-v2
$env:DATABASE_URL = "postgresql+psycopg://karier_user:<пароль>@127.0.0.1:5432/karier_test_db"
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m alembic downgrade -1
.\venv\Scripts\python.exe -m alembic upgrade head
```

| Что | До (0015) | После (0016, head) | После down→up |
|---|---|---|---|
| Ревизия | `0016_stage2_equipment` | `0016_stage2_equipment` (head) | `0016_stage2_equipment` |
| Объекты / порты / связи | 4700 / 12135 / 3788 | 4700 / 12135 / 3788 | 4700 / 12135 / 3788 |
| md5 `gis.assets` (11 полей) | `61683ba332809252ad0ca59232ff84f1` | `61683ba332809252ad0ca59232ff84f1` | тот же |
| md5 `gis.links` (14 полей) | `1071954a2247bd3994f26341967ad753` | `1071954a2247bd3994f26341967ad753` | тот же |
| Типы / поля типов | 19 / 24 | 20 (+`razedinitel`) / 26 | 20 / 26 |
| `links.cable_asset_id` + FK + индекс | нет | есть | есть |
| Шаблоны `bkru`/`substation`/`ktp` | `[]` (у `substation` — `[]`) | v2 | те же v2 (сверено JSON) |
| `is_composite` у профилей | `false` | `true` | `true` |

`alembic heads` → **одна голова** `0016_stage2_equipment`. `compare_metadata` (autogenerate) на
тестовой БД — ровно **29** известных baseline-расхождений из `tests/test_migrations.py`; новых
расхождений по `links.cable_asset_id`/`ix_links_cable_asset` нет.

Полный цикл на **пустой** БД (`tests/test_migrations.py`, `TEST_MIGRATION_DATABASE_URL`) в этом
окружении не запускался: у роли `karier_user` нет права `CREATEDB` (`InsufficientPrivilege`),
а отдельной БД под миграции на стенде нет. Вместо него сделан цикл head→down→up на заполненной
`karier_test_db` со сверкой md5 (таблица выше) + проверка drift — это покрывает риск «миграция
накатывается, а откатиться не может». qa_agent может прогнать `tests/test_migrations.py` там, где
есть выделенная БД.

Рабочая `karier_db` — read-only проверка: head `0015_asset_type_fields`, `cable_asset_id` нет,
`razedinitel` нет, 37 типов, 12 объектов. Миграция на неё **не запускалась**.

## 4. API-контракты этапа 2

Все новые точки — additive; старые маршруты и поля не менялись. Ошибки — прежний problem+json
(`type/title/status/code/detail/instance/request_id`, `fields`/`field_labels` для 422).

### 4.1 `POST /api/schema/composite` (admin) — блок + ячейки (+ разъединитель)

Тело:

```json
{"type_code": "bkru", "name": "БКРУ-3", "x": 320, "y": 180, "cells_per_section": 17, "code": "BKRU-3"}
```

* `type_code` — код активного типа; `name` — 2…255; `x`,`y` — **пиксели холста схемы** (не метры
  карты; старый `/api/composites/place` продолжает принимать метры);
* `cells_per_section` — только для настраиваемых шаблонов (ПС), 1…50 (Pydantic `ge/le` → 422);
  default берётся из шаблона (17). Для БКРУ/КТП параметр → **422 `composite.not_configurable`**;
* `code` — необязательный код блока, иначе генерируется (`BKRU-N`).

Ответ `201`:

```json
{
 "id": "…", "code": "BKRU-3", "name": "БКРУ-3", "type_code": "bkru",
 "schema_x": 320.0, "schema_y": 180.0, "template_version": 2, "children": 6,
 "block": {"id":"…","code":"BKRU-3","name":"БКРУ-3","type_code":"bkru","schema_x":320.0,"schema_y":180.0},
 "cells": [
   {"id":"…","code":"CELL-28","name":"Яч. №1 (Вводная)","type_code":"cell",
    "cell_kind":"in","cell_no":1,"section_no":1,"status":"off","grounded":false,
    "voltage_kv":6.0,"local_x":60.0,"local_y":140.0},
   {"…":"…"}
 ],
 "sections": [
   {"section_no":1,"label":"Секция 1","voltage_kv":6.0,"cells":["…4 ячейки…"]},
   {"section_no":2,"label":"Секция 2","voltage_kv":6.0,"cells":["…2 ячейки…"]}
 ],
 "disconnector": null
}
```

Для КТП: `cells: []`, `sections: []`, `children: 1`,
`disconnector: {"id":"…","code":"RAZEDINITEL-1","name":"Вводной разъединитель","type_code":"razedinitel","cell_kind":"in","status":"off","grounded":false}`,
`disconnector_id` — тот же id на верхнем уровне ответа (для приёмки/UI).
Ячейки создаются `status="off"` (включение — кнопкой/`toggle`), блок — `status="on"`,
`schema_role` дублируется в старых значениях (`in`→`incoming`, `out`→`outgoing`, `sectional`→`section`).
Всё создаётся **одной транзакцией**: при ошибке не остаётся «полублока» (используется
`gis.create_asset(..., commit=False)`, коммит один).

Семантика `cells_per_section` для ПС: при `n ≥ 2` секция = 1 `in` + `(n−2)` `out` + 1 `sectional`
(итого ровно `n`); при `n = 1` — только вводная. Нумерация `cell_no` сквозная по блоку
(БКРУ 1…6; ПС 1…34 для двух секций по 17), `section_no` — номер секции.

### 4.2 `POST /api/assets/{asset_id}/toggle` (право `asset.status.edit`)

Тело необязательно: `{"state": "on"|"off", "reason": "…"}`; без тела — переключение
(`on`→`off`, иначе `on`). Разрешено только для ячеек (`cell_kind` задан) и объектов класса
`switching`; иначе **422 `asset.not_switchable`**. Нет права — **403 `perm.denied`**
(у роли `viewer` права нет, у `operator` есть).

Ответ:

```json
{
 "asset_id": "…", "code": "CELL-27", "name": "Яч. №1 (Вводная)", "cell_kind": "in",
 "status": "on", "previous_status": "off", "changed": true, "grounded": false,
 "energized": true, "voltage_kv": 6.0, "nominal_voltage_kv": 6.0, "topology_energized": false
}
```

* `energized` — оперативное «под напряжением» для кнопки/цвета: `status == "on" and not grounded`;
  `voltage_kv` — номинал при включении, иначе `0.0` (номинал: `attrs.voltage_kv` ячейки → вводный
  порт → любой порт; для ПС секция 1 = 35 кВ, секция 2 = 6 кВ);
* `topology_energized` — достижимость от источника по графу связей (может быть `false`, пока
  ячейка не подключена — это честное состояние схемы, UI красит по `energized`);
* аудит: `audit.audit_log.action = "asset.toggled"`, `entity="asset"`, `entity_id`, актор
  (`actor_id/actor_tab_no/actor_role`), `detail = "CELL-27: off → on"`, `payload =
  {"from_state","to_state","reason","energized","voltage_kv","grounded","cell_kind","changed"}`;
* дополнительно пишется журнал `gis.switching_ops` (`status_on`/`status_off`, from/to, actor) —
  совместимо с журналом Спринта 4 и офлайн-синхронизацией.

### 4.3 Кабельный учёт

`GET /api/cables?lifecycle_status=installed|reserve|repair&q=…&limit=…` (чтение — любой
авторизованный). Отдаёт **массив** кабелей (типы класса `cable`; `lifecycle_status` NULL у старых
строк трактуется как `installed`). Невалидный статус → **422 `validation.failed`**.

```json
[{"id":"…","code":"CABLE-1","name":"Кабель Ф-7К","type_code":"cable","status":"off",
  "lifecycle_status":"installed","cable_mark":"Ф-7К","section_mm2":35.0,"length_m":120.0,
  "voltage_kv":null,"link_id":"…","link_label":"ф.7К","link_state":"connected",
  "installed_on":"Ф-7К","from_asset":{"id":"…","code":"CELL-28","name":"Яч. №2 (Отходящая)",
  "type_code":"cell","type_icon":"▫","status":"off"},"to_asset":{…},
  "attrs":{…},"version":3,"updated_at":"…","warnings":[]}]
```

`POST /api/cables/{cable_id}/install` (право `asset.status.edit`), тело
`{"link_id": "…"} | {"asset_id": "…"}`, опционально `cable_mark`, `length_m`,
`cross_section_mm2`, `reason`:

* `link_id` — ставит кабель на участок: `links.cable_asset_id = cable.id`,
  `cable_status="in_work"`, денормализация `cable_mark/length_m/cross_section_mm2` из карточки;
  кабель → `lifecycle_status="installed"`; ответ `{cable, link_id, link_label}`;
* `asset_id` — установка на объект: если у объекта ровно одна свободная кабельная связь
  (`link_type in (cable, overhead)`, `cable_asset_id IS NULL`) — ставится на неё; если связи нет —
  кабель числится установленным **на объекте** (`attrs.installed_on_asset_id`), `links` не
  выдумывается; несколько свободных связей → **409 `cable.link_ambiguous`** (нужен `link_id`);
* кабель уже стоит на другой связи → **409 `cable.already_installed`**; связь занята другим
  кабелем → **409 `cable.link_occupied`**; не кабель → **422 `cable.not_cable`**;
* аудит: `cable.installed` (`payload.from_status/to_status/link_id/asset_id/reason`, актор — из контекста).

`POST /api/cables/{cable_id}/return` (право `asset.status.edit`), тело необязательно:
`{"status": "reserve"|"repair"|"installed", "link_id": "…", "reason": "…"}` (default `reserve`):
снимает кабель со всех его активных связей (или только с `link_id`), очищает
`links.cable_asset_id`, ставит `link.cable_status="dismounted"`, кабелю — запрошенный статус;
ответ `{cable, detached_links: [uuid…]}`. Аудит: `cable.returned` с прежним/новым статусом и списком
связей. Невалидный статус → **422**. При `status="installed"` кабель остаётся установленным
(связи не снимаются) — это «подтвердить установленным».

### 4.4 Старые API

* `POST /api/composites/place` и `/attach` работают на v2-шаблонах: БКРУ → 6 ячеек,
  ПС → 34 (17+17), КТП → 1 разъединитель; v1-шаблоны (ЯКУ, ЯКНО и др.) обслуживаются прежним
  путём, ответ прежний `{id, name, code, children}`;
* `GET /api/asset-types?with_fields=1` для профилей отдаёт v2-массив в `composite_template`
  (старый клиент видит массив);
* `GET /api/assets/{id}` / `PATCH` / `POST /state` / `/children` / `/topology/graph` — без изменений
  (новые поля `cell_kind/cell_no/section_no/lifecycle_status` добавлены ещё в 0015);
* `POST /api/schema/assets/{id}/cables` (создание кабельной связи) — без изменений; установка
  кабеля-объекта на такую связь делается через `/api/cables/{id}/install {"link_id": …}`.
* `GET /api/links` / `PATCH /api/links` — в `LinkOut` добавлены **nullable** поля
  `cable_asset_id` и `cable_asset` (id/код/имя/тип/статус): клиент и приёмка видят, что кабель
  установлен на участок, не читая БД напрямую. Старые ключи не менялись.

## 5. Ручные проверки на `karier_test_db` (TestClient, созданные объекты удалены)

### 5.1 БКРУ

```
type_code=bkru, name=БКРУ-ТЕСТ → 201
children=6, cell_kind=[in, out, out, sectional, out, in],
cell_no=[1,2,3,4,5,6], section_no=[1,1,1,1,2,2],
sections=[(1,"Секция 1",4),(2,"Секция 2",2)], template_version=2,
schema_x/schema_y=100/200
```

### 5.2 ПС 35/6 (по умолчанию)

```
type_code=substation, name=ПС-ТЕСТ → 201, children=34
section 1: 17 ячеек = in + 15×out + sectional, label «Секция 1 (35 кВ)»
section 2: 17 ячеек = in + 15×out + sectional, label «Секция 2 (6 кВ)»
cell_no: 1…34 (сквозные), voltage_kv: 35.0 (секция 1) / 6.0 (секция 2)
```

### 5.3 `cells_per_section`

`cells_per_section=10` → children=20, по 10 на секцию (in + 8×out + sectional);
`cells_per_section=3` → по секции `in, out, sectional`; `0`/`51` → 422 `validation.failed`;
КТП + `cells_per_section` → 422 `composite.not_configurable`.

### 5.4 КТП

```
type_code=ktp → 201, children=1, cells=[], sections=[],
disconnector={id:…, code:RAZEDINITEL-1, name:"Вводной разъединитель",
              type_code:"razedinitel", cell_kind:"in", status:"off", grounded:false}
```
В БД: тип `razedinitel` (`equipment_class=switching`), объект — дочерний (`parent_asset_id`,
`schema_block_id` = блок), `cell_kind=in`.

### 5.5 Переключение

```
POST /api/assets/{cell}/toggle {"state":"on"}  → 200 {status:on, energized:true, voltage_kv:6.0, grounded:false}
POST /api/assets/{cell}/toggle {"state":"off"} → 200 {status:off, energized:false, voltage_kv:0.0, nominal_voltage_kv:6.0}
POST /api/assets/{cell}/toggle (без тела)      → 200 {status:on}
POST /api/assets/{ktp_disconnector}/toggle {}  → 200 {status:on}
POST /api/assets/{pole}/toggle                 → 422 asset.not_switchable
POST /api/assets/{cell}/toggle (operator)      → 200 on
POST /api/assets/{cell}/toggle (viewer)        → 403 perm.denied
POST /api/cables/{id}/install (viewer)         → 403 perm.denied
```

Аудит (фактическая строка `audit.audit_log`):
`asset.toggled`, актор `000001`, `payload {"from_state":"off","to_state":"on","energized":true,"voltage_kv":6.0,…}`,
`detail "CELL-27: off → on"`; запись в `gis.switching_ops` создана.

### 5.6 Кабели

```
POST /api/assets {type_code:cable, attrs:{cable_mark:"Ф-7К",length_m:120,section_mm2:35}} → 201
POST /api/schema/assets/{cell1}/cables {to_asset_id:cell2} → 201 (связь 6 кВ)
POST /api/cables/{cable}/install {"link_id":…} → 200
  → links.cable_asset_id заполнен; кабель lifecycle_status=installed;
    ответ cable.link_id/link_label/installed_on="Ф-7К"
GET /api/cables?lifecycle_status=installed → 200, кабель в списке с link_id/from_asset/to_asset
POST /api/cables/{cable}/return {"status":"reserve"} → 200 {lifecycle_status:reserve, detached_links:[…]}
GET /api/cables?lifecycle_status=reserve → 200, кабель в списке; links.cable_asset_id=NULL
POST /api/cables/{cable}/install {"asset_id":…} → 200 (установка на объект: installed_on="CELL-33")
POST /api/cables/{cable}/return {"status":"repair"} → 200 lifecycle_status=repair
GET /api/cables?lifecycle_status=bogus → 422 validation.failed
```

Аудит: `cable.installed` (`from_status/to_status/link_id/asset_id`), `cable.returned`
(`from_status/to_status/links`), актор — `000001`.

### 5.7 Идемпотентность сида

`python -m app.seed_equipment_model` на прогретой тестовой БД: все счётчики `0`
(классы/вкладки/поля/ячейки/кабель/шаблоны/разъединитель) — повторный запуск no-op.

## 6. Регресс

| Команда | Результат |
|---|---|
| `pytest -q tests/test_equipment_fields.py tests/test_schema_builder.py` (verify-контракт) | **24 passed** |
| `pytest -q tests/test_gis_api.py tests/test_sprint12_api.py tests/test_api_contract_validation.py tests/test_admin_api.py tests/test_topology_api.py tests/test_ux_api.py tests/test_final_api.py tests/test_schema_blocks.py tests/test_blocks_s18.py tests/test_blocks_s20.py tests/test_blocks_s21.py tests/test_line_builder.py tests/test_gost_schema.py` | **82 passed** |
| `alembic upgrade head; downgrade -1; upgrade head` (на `karier_test_db`) | exit 0, данные целы (§3) |
| `alembic heads` | одна голова `0016_stage2_equipment` |
| `compare_metadata` vs модели | 29 известных baseline-расхождений, новых нет |
| `python -c "from app.main import app; print([r.path …])"` | `/api/assets/{asset_id}/toggle`, `/api/cables`, `/api/cables/{cable_id}/install`, `/api/cables/{cable_id}/return`, `/api/schema/composite` (+ старые `/api/composites/place`, `/api/composites/{parent_id}/attach`, `/api/schema/assets/{asset_id}/cables`) |

Полный прогон pytest и приёмка — за qa_agent.

## 7. Файлы и хеши (SHA-256, от `C:\karier\karier`)

| Файл | Размер | SHA-256 |
|---|---|---|
| `backend-v2/alembic/versions/0016_stage2_equipment.py` (новый) | 14928 | `a5de5fb5c776a25a8c612613fa93c92751510488eff835c42ea88aa0d2992a9e` |
| `backend-v2/app/services/equipment_templates.py` (новый) | 24833 | `b4584e7553b56c575280a30214e7dd23a5d6fbc92f2326ad7abc69ca808cd89a` |
| `backend-v2/app/services/cables.py` (новый) | 16790 | `0163d22f80d6c524428438ee06c0aa999808dd7988d4c405a491402e3cc249f7` |
| `backend-v2/app/schemas/equipment.py` (новый) | 6070 | `9db2e4089bee1360068acc0dee32b8d82f52d8adcac7c589139aa1374d66f561` |
| `backend-v2/app/api/routers/cables.py` (новый) | 3307 | `d0aadff1d1b6336ef3720bb8e569c943728c5e12a188c97bc01841ead0932698` |
| `backend-v2/app/services/composite.py` | 15270 | `cc1ad97f503a501f965e9673d5137dc34d70c11cfc8dd4c9931040354faaf963` |
| `backend-v2/app/services/state.py` | 9976 | `131256c20c43d51a650fe2a0bfa8ac0de3709e9f1fb702085dd643cc9fb7a1fc` |
| `backend-v2/app/services/gis.py` | 37090 | `aa767b923f32d8d07a2d2c90a2fac9fc0868766dcc541bdfa8cbc97c57aca990` |
| `backend-v2/app/models/topology.py` | 7628 | `25a6a90a95e11a09f4ceb8248bf53bf588873099e4a885534568c43f2e202546` |
| `backend-v2/app/api/routers/schema_blocks.py` | 16452 | `ea1ab16aa696cd67e9b4cf64ce487c4378e547ee080d40432b4680621a83f7d2` |
| `backend-v2/app/api/routers/gis.py` | 36573 | `325033f3e6a83b24f14f3b7d8d307d9673d74fb2465481b71e24e7b8cdc8060b` |
| `backend-v2/app/main.py` | 9031 | `fcbf34a9970c6c966c05aef0fa1d9f2622a91ce5d5c8d558db1d0bdc531b8972` |
| `backend-v2/app/seed_equipment_model.py` | 3502 | `02b81e8abfae07cb2e38986cc548e60f5053742c2e93a0db8de9b7557f81a853` |
| `backend-v2/app/schemas/gis.py` | 28405 | `e4781d65243c9bf514baa5992943114ed9f248d7f0f0f0106766a0db27e464dd` |
| `backend-v2/app/services/links.py` | 11635 | `6d39ff50b3621cfbd43ce143692531dec5ad4354767f9f4feb6a5f781e5ebe53` |

Не менялись: `tests/`, `src-v2/`, `backend-v2/.env`, `backend-v2/alembic.ini`, рабочие сиды
(`seed_gis.py`, `seed_schema_blocks.py`). Рабочая `karier_db` — на `0015`, без новых колонок/типов.

## 8. Для ui_agent: что уже есть на бэкенде

1. **Мастер создания**: `GET /api/asset-types?with_fields=1` → у БКРУ/ПС/КТП
   `is_composite=true`, `composite_template` v2 (массив: мета + секции); счётчики для предпросмотра
   берутся из меты/секций. Сохранение — `POST /api/schema/composite`.
2. **Схема/карточка**: `POST /api/assets/{id}/toggle` (тело `{"state":"on"|"off"|null,"reason":…}`).
   Цвета: `energized=true` → красный (под напряжением), `energized=false` → зелёный
   (обесточено/заземлено); `grounded=true` тоже зелёный. `voltage_kv` — для подписи «6 кВ / 35 кВ».
   Ошибки: 403 без `asset.status.edit`, 422 `asset.not_switchable` для не-ячеек.
3. **Список кабелей**: `GET /api/cables?lifecycle_status=installed|reserve|repair` — массив
   `CableOut` (марка/сечение/длина/линия/объекты, `installed_on`); установка/снятие —
   `POST /api/cables/{id}/install` (`link_id` или `asset_id`), `POST /api/cables/{id}/return`
   (`{"status":"reserve"|"repair"}`). В карточке кабеля — поле `lifecycle_status`.
4. `composite_template` теперь **v2** у БКРУ/ПС/КТП: если старый экран «Типы» редактирует состав,
   его нужно переключить на новый формат (иначе сохранение из старой формы затрёт v2 →
   `/api/schema/composite` всё равно продолжит работать: при отсутствии v2 он берёт встроенный
   профиль по коду/названию типа).

## 9. Осталось на следующие этапы (вне t1)

* `GET /api/equipment/classes` (счётчики по вкладкам) — не входило в t1;
* паспортные поля `serial_no/manufacturer/model/commissioned_on/warranty_until` и
  `assets.location_kind` из плана 31 §3.3 — отдельная миграция;
* `POST /api/cables` (создание кабеля сразу «в запас» с маркой/сечением) — сейчас кабель
  создаётся обычным `POST /api/assets` с `type_code=cable`;
* тесты этапа 2 (`tests/test_equipment_stage2.py`) и полный прогон — qa_agent.
