# Фикс: «Проверьте атрибуты объекта» при создании ячеек в рамке

Дата: 26.11.2026 · файлы: `backend-v2/app/services/{gis,schema_blocks}.py`, `tests/test_schema_builder.py`

## Симптом

В рабочей БД при добавлении ячейки/пачки ячеек в контур (рамку) API отвечал:
`422 validation.failed` — «Проверьте атрибуты объекта».

## Причина

1. После «чистого листа» в `karier_db` нет типа с кодом `cell`: он деактивирован/удалён.
2. Резолвер `_resolve_type()` при создании ячейки идёт по цепочке `cell → yacheyka → tcell → yach`, не находит их и берёт **первый активный тип с «ячейк» в названии** — им оказался «Ячейка БКРУ-1» (`yacheyka_2`).
3. У этого типа заполнены `required_attrs` (`power_kw`, `voltage_in_kv`, `voltage_out_kv`).
4. Ячейка схемы создаётся с `attrs={sequence_no, section…}` — обязательных полей нет → `gis.validate_attrs()` возвращает ошибки → 422.

На тестовой БД баг не воспроизводился: там есть общий тип `cell` без `required_attrs`, поэтому пачка ячеек создавалась.

## Исправление

`gis.create_asset()` получил параметр `validate_attributes: bool = True`.
Дочерние элементы блока (`schema_blocks._create_child`, через него работают и `POST …/cells`, и `POST …/cells/bulk`) создаются с `validate_attributes=False`: ячейка — визуальный элемент схемы, её электрические параметры заполняются позже в карточке объекта. Создание через реестр (`POST /api/assets`) по-прежнему требует атрибуты.

## Регрессионный тест

`tests/test_schema_builder.py::test_bulk_cells_skip_required_attrs_of_cell_type`:
- создаётся тип с `required_attrs=["power_kw"]`;
- пачка ячеек с этим `type_code` → **201**;
- тот же тип через `POST /api/assets` без attrs → **422** с `fields.power_kw`.

## Проверки

- `pytest`: 28 passed (schema_builder + line_builder + blocks s18/s20/s21).
- Живая проверка на рабочей БД: временный контур → `POST …/cells/bulk {count:2, section_size:1}` → **201**, секции «Секция 1/2»; ячейки и контур удалены после проверки.
- API перезапущен, фикс активен.
