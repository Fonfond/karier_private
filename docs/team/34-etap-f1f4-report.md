# F1 + F4 — итог исправлений и приёмка

Дата: 26.11.2026 · команда `karier-equipment-stage2` · вердикт t8: **PASS**

## 1. F1 — схема мгновенно перекрашивается после toggle из карточки

**Причина:** `AssetSheet` менял только свой локальный объект, `MapPage` не знал о переключении, а `SchemaView` красит ячейки по `assetStates` из реестра; у ячеек только что созданного мастером блока записей вообще не было.

**Исправление (только `src-v2/src`):**
- `AssetSheet` → новый проп `onStateChanged` (из `StateControls.onChanged` и `ChildrenModal.onChanged`);
- `MapPage` → `handleStateChanged`: точечный `powerOverrides` + `applyPowerState(assets)` + тихий `loadGraph`; `assetStates = overrides + ячейки реестра`;
- `lib/power.ts` → чистая `applyPowerState` (+4 теста);
- `SchemaView` → сортировка ячеек составных блоков по `section_no`/номеру (порядок `children` от API не «прыгает»).

**Приёмка (Edge/CDP, production dist + backend на тестовой БД, 17/17 PASS):**
- БКРУ создан из UI (6 ячеек); «Включить» в карточке → схема **сразу** красная (`rgb(240,68,56)`, «под напряжением»), карточка — красный бейдж; «Отключить» → схема и карточка зелёные (`rgb(34,197,94)`);
- **без перезагрузки** (`window.__qaMarker='no-reload'`, `performance navigation entries=1`);
- toggle на самой схеме работает; transform камеры идентичен на 4 замерах — камера не сбрасывается;
- console errors: none, API ≥400: 0.

## 2. F4 — снятие кабеля очищает данные связи

**Исправление (`backend-v2/app/services/cables.py`):**
- `_detach` обнуляет `cable_asset_id`, `cable_mark`, `length_m`, `cross_section_mm2`, ставит `cable_status='dismounted'`;
- аудит `cable.returned`: `cleared_fields=[cable_asset_id,cable_mark,length_m,cross_section_mm2]` + `cleared` с прежними значениями, detail «очищены cable_mark/length_m/cross_section_mm2»;
- `install` по-прежнему заполняет денормализацию; `return {status:"installed"}` связь не снимает; повторный `return` идемпотентен.

**Приёмка (API, 14/14 PASS):**
- install → `cable_asset_id` + `cable_mark='ПР-0F80D8'`, `length=90.0`, `cross_section=25.0`, `in_work`;
- return reserve → все четыре **NULL**, `dismounted`, кабель reserve;
- повторный return → 200, `detached_links=[]`, `cleared=[]`; повторный install снова заполняет; return repair → NULL, `to_status=repair`.

## 3. Регресс

| Проверка | Результат |
|---|---|
Полный pytest | **227 passed, 3 skipped, 0 failed** (301 с, exit 0) |
Frontend | typecheck 0, build 0 (516 модулей, 4,95 с), **vitest 82 passed** (`power.test` 15, +4) |
Хеши | app 80 ф. `9999cfd4…`, tests 34 ф. `d528029a…`, src-v2/src 71 ф. `ed9f98f3…`, конфиги 8 ф. `c1d7a427…` — до/после совпали |
Тестовая БД | после прогона baseline (5049/585, 3788/3737, `cable_asset_id NOT NULL=0`), сервисы 8004/5182 остановлены |
Рабочая БД | `karier_db` на 0016, не менялась этой задачей |

## 4. Рабочий стенд

- стек перезапущен: API 8001 + Vite 5174, сайт 200, `health/ready=ok`;
- маршруты `/api/assets/{id}/toggle` и `/api/cables` доступны;
- рабочая БД: 0016, 12 объектов, 12 связей.

**Как проверить:** `Ctrl+F5` → «Карта» → «Схема» → «▤ По шаблону» → создать БКРУ → открыть ячейку → «Включить»: цвет на схеме меняется сразу; затем «Кабели» → установить кабель на связь → «Снять в запас»: в карточке связи не остаётся марки/длины/сечения.

## 5. Оговорки (не блокируют)

1. После снятия у связи остаётся маркер `cable_status='dismounted'` — данных кабеля нет, это признак «снят».
2. `return {status:"installed"}` — подтверждение с сохранением связи и данных.
3. 3 теста `test_migrations.py` пропущены (нужна отдельная БД).
4. F1 проверен на «новых» ячейках (корневой сценарий); тихий `loadGraph` камеру не сбрасывает.

## 6. Артефакты

`docs/team/34a-f1-fix.md` (+5 скриншотов), `34b-f4-fix.md`, `34c-fix-tests.md`, `34d-f1f4-acceptance.md` (+7 скриншотов); тесты `backend-v2/tests/test_stage2_equipment.py` (13 тестов).
