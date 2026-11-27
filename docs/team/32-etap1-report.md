# Этап 1 модели оборудования — итог и раскатка

Дата: 26.11.2026 · команда `karier-equipment-model` (db_agent, ui_agent, qa_agent) · вердикт t4: **pass**

## 1. Что сделано по агентам

| Задача | Агент | Результат |
|---|---|---|
**t1** | db_agent | миграция `0015_asset_type_fields`: `gis.asset_type_fields` (24 поля у 19 типов), `equipment_class` + `group_code` с CHECK, `cell_kind/cell_no/section_no` (+2250/+454 перенесено), кабельный `lifecycle_status` CHECK(installed/reserve/repair), тип `cable`; API `?with_fields=1` и валидация 422 с русскими `field_labels`; двойная запись `attr_schema↔fields` |
**t2** | ui_agent | динамическая форма создания: вкладки классов → модель → поля паспорта (число/текст/да/нет/дата/список, единицы, `*`), клиентская валидация, разбор серверного 422 по полям; +28 vitest |
**t3** | qa_agent | `tests/test_equipment_fields.py` — 10 тестов: 422 «отходящая с пустым power_kw» с понятным текстом, 201 с паспортом, контракт полей, обратная совместимость, PATCH, кабель; полный прогон **214 passed / 3 skipped** дважды |
**t4** | qa_agent | приёмка: хеши 213 файлов до/после совпали, миграции up→down→up, API 422/201, браузерный смоук (7 вкладок, поля КТП, клиентская блокировка), отчёт `32d-etap1-acceptance.md` |

## 2. Раскатка на рабочую БД (сделано после приёмки)

- бэкап: `C:\karier\.local\backups\karier_db-before-0015-20261126-190742.dump` (0,85 МБ);
- `alembic upgrade head` на `karier_db` → **0015**, 37 типов, 80 полей, тип `cable`;
- `python -m app.seed_equipment_model` — идемпотентно, добивки не потребовалось;
- стек перезапущен: API 8001 + Vite 5174, сайт 200;
- проверка API: `GET /api/asset-types?with_fields=1` → 20 активных типов, у всех класс/группа, 58 полей; у КТП — «Мощность, Полная мощность, Напряжение на входе/выходе»;
- браузер (скриншот `.local/browser/shots/82-registry-dynamic-prod.png`): вкладка «Трансформаторы и сборки», паспорт с полями и единицами, обязательные помечены `*`, ошибок консоли/API нет.

## 3. Ограничения и что осталось

1. `MapPage` / `AddToSchemaPanel` не используют `DynamicFields`: на карте и схеме паспорт не заполняется (422 объясняется, но полей нет) — кандидат Этапа 2.
2. Демо-сид тестовой БД и рабочая БД разошлись по `required_attrs` у КТП — после раскатки 0015 на рабочую БД это неактуально.
3. Этап 2: шаблоны ячеек (БКРУ-6, ПС 35/6 — 17 на секцию), API смены статуса с возвратом напряжения, кнопки «Включить/Отключить», красный/зелёный на схеме/в карточке/списках, аудит, `/api/cables` (installed/reserve/repair, install/return).

## 4. Артефакты

`docs/team/32a-db-migration.md`, `32b-ui-form.md`, `32c-etap1-tests.md`, `32d-etap1-acceptance.md`; тесты: `backend-v2/tests/test_equipment_fields.py`; UI: `src-v2/src/lib/assetFields.ts`, `components/asset/DynamicFields.tsx`, `RegistryPage.tsx`.
