# Этап 3 «Продвинутая интерактивность схемы»: БД и API (db_agent)

Дата: 27.11.2026 · миграция `0017_schema_block_size` · проверено на `karier_test_db`
Рабочая БД `karier_db` **не менялась**: read-only проверка после всех прогонов —
ревизия `0016_stage2_equipment`, колонок `gis.assets.schema_width/schema_height` нет,
19 объектов (см. §3.3).

## 1. Итог

| Требование контракта t1 | Статус | Чем подтверждено |
|---|---|---|
| Миграция 0017 additive: `gis.assets.schema_width` / `schema_height` (`numeric(10,2)`, nullable, CHECK > 0); up→down→up на `karier_test_db`, данные целы | ✅ | §2, §3.1: ревизия `0017_schema_block_size`, до/после цикла 5049 объектов / 12965 портов / 3788 связей; CHECK отклоняет 0 и −5 |
| `GET /api/topology/graph` отдаёт `schema_width`/`schema_height` блоков (и совместимые `width`/`height`); `AssetOut` — тоже | ✅ | §4.1, §5.1: контур 360×240 → graph `schema_width=360`, `schema_height=240`; после ресайза 480×320 |
| `PUT /api/topology/layout` принимает `width`/`height` блока и `local_x`/`local_y` ячейки, атомарно сохраняет в БД | ✅ | §4.2, §5.2–5.3: ресайз → `gis.assets.schema_width=480`; ячейка 60/40 и 180.5/220 → `schema_local_x/y` и graph `blocks[].children[].local_x/y` |
| Серверная валидация: координата ячейки вне `0…width`/`0…height` → 422 с понятным текстом; размеры < минимума → 422; частично некорректный payload не меняет раскладку | ✅ | §5.4–5.6: `layout.out_of_bounds`, `layout.size_too_small`, `layout.not_block`, `layout.not_cell`; атомарность проверена по БД |
| `POST /api/links` принимает `from_port_id`/`to_port_id` вложенных ячеек: block→cell и cell→cell работают, block→block не сломан; чужие/архивные порты → 404/422 | ✅ | §5.8: 201/201/201; архивный порт → 422 `link.asset_archived`, неизвестный/чужой → 404 |
| Координаты ячеек — существующие `schema_local_x/schema_local_y`; новых `schema_cell_x/y` нет | ✅ | §2.4: миграция добавляет только 2 колонки размера; `grep schema_cell_` по коду — 0 совпадений |
| Старые API совместимы; регресс-поднабор pytest зелёный | ✅ | §7, §8: контрактный поднабор 37 passed; полный прогон **227 passed, 3 skipped** |
| Отчёт с контрактами и хешами | ✅ | этот документ (§4, §9) |

## 2. Миграция `0017_schema_block_size`

Файл: `backend-v2/alembic/versions/0017_schema_block_size.py`, `down_revision = 0016_stage2_equipment`.
Только additive: две nullable-колонки и два CHECK; ни одна таблица/колонка/строка не удаляется.

### 2.1 Колонки

```
gis.assets.schema_width   numeric(10,2) NULL  CHECK (schema_width  IS NULL OR schema_width  > 0)
gis.assets.schema_height  numeric(10,2) NULL  CHECK (schema_height IS NULL OR schema_height > 0)
```

* **nullable**: у ячеек и одиночных символов размера нет — их рисует клиент по символу и
  `block.width ?? 320` / `block.height ?? 220` (текущий `SchemaView.tsx`). NULL = «размер не
  задавали», а не «нулевой блок».
* **CHECK > 0** (а не `>= 0`): 0/отрицательная сторона ломает NodeResizer и подписи; после
  миграции такие значения не записать даже SQL-ом.
* Модель: `app/models/gis.py::Asset` — те же колонки и `CheckConstraint` с теми же именами
  (`ck_assets_schema_width_positive`, `ck_assets_schema_height_positive`).

### 2.2 Досыпка (backfill) размеров контуров

До этапа 3 размер контура жил только в `attrs.contour_w` / `attrs.contour_h`
(`services/schema_blocks.py::create_contour`). Миграция переносит его в колонки:

```sql
UPDATE gis.assets
   SET schema_width  = round((attrs ->> 'contour_w')::numeric, 2),
       schema_height = round((attrs ->> 'contour_h')::numeric, 2)
 WHERE schema_width IS NULL AND schema_height IS NULL
   AND jsonb_typeof(attrs -> 'contour_w') = 'number'
   AND jsonb_typeof(attrs -> 'contour_h') = 'number'
   AND (attrs ->> 'contour_w')::numeric > 0 AND (attrs ->> 'contour_h')::numeric > 0
   AND (attrs ->> 'contour_w')::numeric <= 99999999 AND (attrs ->> 'contour_h')::numeric <= 99999999;
```

Только в пустые колонки и только положительные числа — данные админа не перезаписываются.
`attrs.contour_w/h` **остаются** (двойная запись): их читают старый клиент и отчёты, а
`create_contour` пишет оба места разом. Код чтения (`gis.block_size`) при NULL в колонках
падает обратно на `attrs`, поэтому объекты, созданные старым кодом/импортом, тоже видны.

### 2.3 Откат (downgrade)

Снимаются два CHECK и две колонки. Размеры контуров при этом остаются в `attrs.contour_w/h`,
объекты, порты, связи и раскладка `schema_x/y`, `schema_local_x/y` не затрагиваются.

### 2.4 Почему НЕТ `schema_cell_x/y`

Координаты ячейки внутри блока уже хранятся в `gis.assets.schema_local_x` / `schema_local_y`
(миграция 0011, заполняются `composite.py`, `groups.py`, `schema_blocks.relocate`). Дублирующие
колонки не добавлялись: API `PUT /api/topology/layout` пишет **именно** `schema_local_x/y`, а
graph отдаёт их как `blocks[].children[].local_x/local_y`. Проверка:
`grep -rn "schema_cell_" backend-v2/app backend-v2/alembic` — пусто.

## 3. Проверка миграции на `karier_test_db` (рабочая БД не тронута)

### 3.1 Команды

`alembic` берёт DSN из `settings.DATABASE_URL` (`backend-v2/.env` → `karier_db`), поэтому база
подменяется переменной окружения — иначе миграция уйдёт в рабочую БД:

```powershell
cd C:\karier\karier\backend-v2
$env:DATABASE_URL = "postgresql+psycopg://karier_user:<пароль>@127.0.0.1:5432/karier_test_db"
.\venv\Scripts\python.exe -m alembic upgrade head      # 0016 -> 0017
.\venv\Scripts\python.exe -m alembic downgrade -1      # 0017 -> 0016
.\venv\Scripts\python.exe -m alembic upgrade head      # 0016 -> 0017 (повторно)
```

### 3.2 Результаты

| Что | До (0016) | После upgrade (0017) | После downgrade −1 | После повторного upgrade |
|---|---|---|---|---|
| Ревизия | `0016_stage2_equipment` | `0017_schema_block_size` | `0016_stage2_equipment` | `0017_schema_block_size` |
| `gis.assets` | 5049 | 5049 | 5049 | 5049 |
| `gis.asset_ports` | 12965 | 12965 | 12965 | 12965 |
| `gis.links` | 3788 | 3788 | 3788 | 3788 |
| `schema_width/height` | — | есть (`numeric(10,2)`, nullable) | нет | есть |
| CHECK-и | — | 2 (`ck_assets_schema_width_positive`, `ck_assets_schema_height_positive`) | нет | 2 |
| Досыпка контура `attrs.contour_w=360/h=240` | — | `360.00 / 240.00` | — | `360.00 / 240.00` |

Проверка CHECK (на временном контуре, строка после проверки удалена):
`schema_width=0` → `violates check constraint "ck_assets_schema_width_positive"`;
`schema_width=-5` → то же; `schema_width=500/schema_height=300` → принято.

`alembic check` на `karier_test_db` (head 0017) показывает **ровно известный baseline-дрейф**
S-10 (29 операций: 4 индекса, 2 FK, 23 комментария таблиц из `tests/test_migrations.py`) и
**ни одной** операции по `schema_width/schema_height` — модель и миграция согласованы.

### 3.3 Рабочая `karier_db` (read-only)

```
rev: 0016_stage2_equipment     assets: 19     new columns: []     contours with contour_w: 0
```

⚠️ Пока `0017` не накатана на рабочую БД, новый код на ней не запустится: модель `Asset`
содержит `schema_width/schema_height`, и любой `SELECT` по `gis.assets` будет ссылаться на
несуществующие колонки. Перед запуском приложения на `karier_db` нужно выполнить
`alembic upgrade head` от её DSN (команды — §10, без подмены `DATABASE_URL`). По контракту t1
рабочую БД в этой задаче не трогали — момент накатывания согласует капитан/приёмка.

## 4. Контракты API для UI (этап 3)

### 4.1 `GET /api/topology/graph`

`blocks[]` (`GraphBlockOut`) — добавлены два поля, старые сохранены:

| Поле | Тип | Смысл |
|---|---|---|
| `schema_width` | `float \| null` | `gis.assets.schema_width`; `null` — размер не задавали (клиент берёт свой дефолт) |
| `schema_height` | `float \| null` | `gis.assets.schema_height` |
| `width` | `float \| null` | **то же значение** (обратная совместимость: старый клиент/PDF/снимки читают `width`) |
| `height` | `float \| null` | то же значение |

`blocks[].children[]` — без изменений: `local_x`/`local_y` (это `schema_local_x/schema_local_y`).
`nodes[].ports[]` — без изменений (`schema_x/schema_y` в долях 0…1).
`GET /api/assets/{id}` (`AssetOut`) дополнительно отдаёт `schema_local_x`, `schema_local_y`,
`schema_width`, `schema_height`.

### 4.2 `PUT /api/topology/layout` (admin, автосейв)

Тело (все поля элемента, кроме `asset_id`, необязательны — присылайте только изменённое):

```json
{
  "items": [
    {"asset_id": "<блок>",  "width": 480, "height": 320},
    {"asset_id": "<ячейка>", "local_x": 60, "local_y": 40},
    {"asset_id": "<узел>",   "x": 300, "y": 200}
  ],
  "ports": [{"port_id": "<порт>", "x": 0.15, "y": 0.85}]
}
```

* `x`/`y` — абсолютные координаты узла на холсте (старый контракт, обязательность снята:
  старый клиент присылает их как раньше, новый может не присылать вовсе).
* `width`/`height` — **только для блока** (ПС/БКРУ/КТП/контур: `schema_block_id IS NULL` и
  `schema_role='block'` либо `attrs.block_code`). Диапазон:
  ширина `120…10000` px, высота `80…10000` px.
* `local_x`/`local_y` — **только для ячейки внутри блока**; пишутся в существующие
  `schema_local_x/schema_local_y`. Допустимый диапазон: `0…schema_width` / `0…schema_height`
  родителя (граница включительно). Если размер блока ещё не задан (`null`), проверка границ
  не выполняется — нечем ограничивать.
* Размер блока из **этого же** payload учитывается при проверке границ его ячеек: можно одним
  запросом и увеличить блок, и подвинуть ячейки.
* Порты — старый контракт (доли 0…1, кламп), неизвестные порты молча пропускаются.

Ответ:

```json
{"updated": 2, "updated_ports": 0, "updated_blocks": 1, "updated_cells": 1, "skipped": []}
```

`skipped` — id объектов, которых нет в живых объектах карьера (архив/чужой карьер), как раньше.
`updated` = число объектов, у которых реально что-то изменилось; элементы без полей игнорируются.

### 4.3 Ошибки раскладки (все 422, `application/problem+json`)

| `code` | Когда | Пример `detail` |
|---|---|---|
| `layout.out_of_bounds` | `local_x/local_y` вне `0…width/height` блока (**новое** значение) | `Ячейка CELL-1: X 481 px выходит за границы блока «Контур РУ-2» (допустимо 0…480 px)` |
| `layout.out_of_bounds` | координата отрицательная | `…X -1 px отрицательная — координаты внутри блока «…» начинаются с 0` |
| `layout.size_too_small` | ширина < 120 px или высота < 80 px | `Блок B-1: ширина 100 px меньше минимума 120 px` |
| `layout.size_too_large` | > 10000 px | `Блок B-1: ширина 20000 px больше предела 10000 px` |
| `layout.not_block` | `width/height` пришли для ячейки/символа | `Объект CELL-1: размер задаётся только для блока схемы (ПС/БКРУ/КТП/контур)` |
| `layout.not_cell` | `local_x/local_y` пришли для блока | `Объект B-1: локальные координаты задаются только для ячейки внутри блока…` |
| `layout.invalid_number` | не число/`inf`/`NaN` | `Блок B-1 (width): ожидается конечное число` |

Атомарность: **вся** валидация идёт до первой записи. Если хотя бы один элемент некорректен —
422 и ни один объект (включая корректные элементы того же payload) не меняется.

Особый случай (важно для автосейва «присылаю всё состояние»): уже сохранённое значение
`local_x/local_y` не пере-валидируется — если значение **не меняется**, оно принимается даже
вне текущих границ блока. Иначе раскладки этапа 2 (ячейки `composite.py` ставятся с шагом
120 px, до `x=660`, при клиентском дефолте блока 320 px) навсегда застряли бы на 422 после
уменьшения блока. Валидируются именно изменения: `690 → 690` при width=300 → 200,
`690 → 691` при width=300 → 422.

### 4.4 `POST /api/links` — порты вложенных ячеек

Связь строится по **портам**, а не по блокам, поэтому вложенность не ограничивает:

| Сценарий | Результат |
|---|---|
| `block → cell` (OUT-порт ПС/БКРУ/контура → IN-порт его ячейки) | 201 |
| `cell → cell` (OUT одной ячейки → IN другой, в т.ч. внутри одного блока) | 201 (`link_type=jumper` попадает в `blocks[].jumpers`) |
| `block → block` (внешние порты двух блоков) | 201 (не сломано) |
| порт вложенной ячейки другого карьера / несуществующий порт | 404 `resource.not_found` / `Порт … не найден` |
| порт объекта в архиве (`gis.assets.deleted_at IS NOT NULL`) | 422 `link.asset_archived` с подсказкой «восстановите объект» |
| IN→IN / один и тот же объект / несовпадение напряжения / дубль / цикл | как раньше: 400/422/409 (`link.bad_direction`, `link.same_asset`, `link.voltage_mismatch`, `link.duplicate`, `link.cycle`) |

Проверка архивных/чужих портов вынесена в `links_service.ensure_ports_linkable()` и вызывается
из роутера `POST /api/links` (публичный API). Внутренние сервисные вызовы (перемычка, цепочка
линии, MCP-инструмент `ai_tools.create_link`) валидируют свой контекст сами и предпроверку не
используют — это сохраняет прежнее поведение внутренних сценариев (регресс `test_mcp_tools.py`).

## 5. Проверка API (живые вызовы на `karier_test_db`)

Скрипт: временный (вне репозитория), `TestClient(app)`, вход `000001/admin`, все созданные
объекты после проверки удалены SQL-ом — в БД снова 5049 объектов.

### 5.1 graph

* новый контур 360×240 → `blocks[].schema_width=360`, `schema_height=240`, `width=360`,
  `height=240`; `GET /api/assets/{id}` → `schema_width/schema_height/schema_local_x/y`;
* `gis.assets.schema_width/height` заполнены уже при создании контура (не только после ресайза).

### 5.2 Ресайз блока

`PUT {"items":[{"asset_id":БЛОК,"width":480,"height":320}]}` → 200,
`updated=1, updated_blocks=1`; graph после → 480×320; **нетронутый объект** (`KTP` из демо):
`version` и `updated_at` не изменились (и в API, и в БД).

### 5.3 Координаты ячеек

`local_x/local_y = 60/40` и `180.5/220` → 200 `updated_cells=2`; graph
`blocks[].children[]` и `gis.assets.schema_local_x/y` совпадают; `local_x == width` (480 при
width=480) принимается (граница включительно).

### 5.4 Границы

`local_x=481` при width=480 → 422 `layout.out_of_bounds` с текстом, где указано 480;
`local_y=-1` → 422; уменьшение блока до 300 → 200; повторная отправка неизменного 690 → 200;
новое 691 при width=300 → 422.

### 5.5 Минимумы и типы объектов

`width=100` → 422 `layout.size_too_small`; `height=50` → 422; `width` для ячейки → 422
`layout.not_block`; `local_x` для блока → 422 `layout.not_cell`.

### 5.6 Атомарность

Payload из двух элементов (валидный `10/10` + невалидный `99999`) → 422; значение валидного
элемента в БД осталось прежним (`60/40`).

### 5.7 Автосейв: 20 последовательных PUT

20 запросов подряд (ресайз блока + перемещение ячейки в каждом) — **20/20 → 200**, ошибок и
таймаутов нет; последнее состояние сохранено (439×319); `version`/`updated_at` нетронутого
объекта в БД не изменились. Латентность (in-process ASGI `TestClient`, включает JWT-аутентификацию,
проверку прав, валидацию и запись в PostgreSQL; без сетевого RTT):

| min | median | **p95** | max |
|---|---|---|---|
| 12.7 мс | 14.3 мс | **15.5 мс** | 16.7 мс |

Транзакция одна на запрос, UPDATE только по фактически изменённым строкам; чтение — один
`SELECT … WHERE id IN (…)` по переданным объектам (+ один запрос родителей ячеек и один по
портам), «весь граф» не читается и не перезаписывается.

### 5.8 Связи

`block→cell` 201, `cell→cell` 201, `block→block` 201; graph `blocks[].jumpers` содержит
cell→cell; архивный порт → 422 `link.asset_archived`; неизвестный порт → 404; порт «чужого
карьера» (`pit_id` не совпадает) → 404.

## 6. Что важно UI-агенты (эксплуатационные правила)

1. Слать в `PUT /api/topology/layout` **только изменённое**: `{asset_id,width,height}` для
   блока и `{asset_id,local_x,local_y}` для ячейки. Элементы без полей игнорируются.
2. При перетаскивании ячейки **клампить** `local_x ∈ [0, width]`, `local_y ∈ [0, height]`
   блока (иначе 422 `layout.out_of_bounds` в автосейве).
3. При ресайзе блока меньше текущего содержимого — либо зажать/пересчитать ячейки в новых
   границах, либо не отправлять неизменившиеся ячейки (они принимаются как есть, §4.3).
4. У ПС/БКРУ/КТП, созданных этапом 2, `schema_width/height` = `null`: клиент рисует их своим
   дефолтом (`320×220` в `SchemaView.tsx`) и отправляет размер при первом ресайзе. Пока размер
   не задан, сервер границы ячеек не проверяет.
5. `width/height` — это размер **прямоугольника блока**, а не холста; ячейки двигаются только
   внутри своего блока (`schema_block_id`), перенос в другой блок — прежний
   `POST /api/schema/assets/{id}/relocate`.

## 7. Совместимость

* `GraphBlockOut.width/height` сохранены и равны `schema_width/schema_height` (fallback на
  `attrs.contour_w/h`, если колонки NULL) — снимки схемы (`schema_snapshots`) и PDF
  (`schema_pdf`) читают те же поля.
* `PUT /api/topology/layout`: `x`/`y` перестали быть обязательными (ослабление), поведение для
  старого payload идентично; ответ дополнен `updated_blocks/updated_cells`.
* `AssetOut` дополнен 4 nullable-полями — старые клиенты их игнорируют.
* `create_contour` пишет размер в колонки **и** в `attrs.contour_w/h` — старые клиенты/отчёты
  читают `attrs` как раньше.
* `links.create_link` принимает те же port-id; изменились только ответы на ошибочные входы
  (архивный порт 422, чужой карьер 404 вместо 400).
* Новых обязательных полей, новых таблиц и дублирующих колонок (`schema_cell_x/y`) нет.

## 8. Регресс pytest

Контрактный поднабор (verify из t1):

```
.\venv\Scripts\python.exe -m pytest -q tests/test_schema_builder.py tests/test_equipment_fields.py tests/test_stage2_equipment.py
→ 37 passed, 545 warnings in 53.08s
```

Полный прогон (`pytest -q`, все тесты `backend-v2/tests`):

```
→ 227 passed, 3 skipped, 638 warnings in 306.85s (0:05:06)
```

Это ровно базовые 227 зелёных тестов; `skipped` — 3 интеграционных теста без внешних
данных/отдельной БД миграций (как и до этапа 3).

> Замечание по флейку: `tests/test_gis_api.py::test_admin_creates_and_deletes_asset` генерирует
> код `TST-{uuid4().int % 10000}`. В `karier_test_db` с прошлых этапов лежат **41** старый
> soft-deleted объект `TST-*` (созданы 03–07.11.2026), поэтому с вероятностью ~0.4% случайный
> код совпадёт с существующим и тест упадёт на `uq_assets_pit_code`. В первом полном прогоне
> этапа 3 так и случилось (коллизия `TST-7098`); повторный прогон — 227 passed. Это не
> регрессия этапа 3: код теста не менялся, а совпавшая строка создана до 27.11.2026
> (`created_at` в `gis.assets`).

## 9. Изменённые файлы и хеши (SHA-256)

| Файл | Строк | SHA-256 |
|---|---|---|
| `backend-v2/alembic/versions/0017_schema_block_size.py` (новый) | 93 | `0f95a3d0b5a9e5c8c34633908f72da1eb895e699b09fda2f8ba7b0b273c12c71` |
| `backend-v2/app/models/gis.py` | 381 | `a1d4c1e5bdac3dff6514115ca9a912ebf83ac3734ec4fe511deccad2fa023f96` |
| `backend-v2/app/schemas/gis.py` | 915 | `d05e81142c626538b92af4eccf97e010fe96c28755094eb958d69adc78bb3ba6` |
| `backend-v2/app/services/gis.py` | 1336 | `bba921b15aab4f59f1fcac5f8ea9acc4228ff09d375704ad9b61c405442a7e0a` |
| `backend-v2/app/services/schema_graph.py` | 220 | `4cd714953531d383272fbacc87d828a58dc5af8f3f64253b4514c2da5ae201c2` |
| `backend-v2/app/services/schema_blocks.py` | 1152 | `40d11a3af1cd6ead2b3e369c42650b2e876660433d0724a3381f1beb055e426d` |
| `backend-v2/app/services/links.py` | 372 | `7f270c2e82beaf6a28fd4e625496fb9a6ae072cc9f1b63222a77ce0f9c2f821d` |
| `backend-v2/app/api/routers/gis.py` | 1025 | `2fd7badab04fffd1f3290052eb21b11d5aaa26ece927f9b4ec71248fb1cb93b5` |

`app/api/routers/gis.py` содержал незакоммиченные правки предыдущих этапов — мой вклад в нём
только `ensure_ports_linkable()` в `POST /api/links` (см. §4.4).

## 10. Команды воспроизведения

```powershell
cd C:\karier\karier\backend-v2
$env:DATABASE_URL = "postgresql+psycopg://karier_user:<пароль>@127.0.0.1:5432/karier_test_db"
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m alembic downgrade -1
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m alembic check          # только baseline-дрейф S-10
.\venv\Scripts\python.exe -m pytest -q tests/test_schema_builder.py tests/test_equipment_fields.py tests/test_stage2_equipment.py
.\venv\Scripts\python.exe -m pytest -q              # полный прогон
```
