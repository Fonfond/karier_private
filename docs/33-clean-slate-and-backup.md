# Чистый лист: что было сохранено и что удалено (09.11.2026)

## 1. Снимок «как было»

Полный дамп базы (включая фотографии, документы, историю, аудит):

```
C:\karier\backups\karier_before_clean_20261109.dump    (~355 МБ, формат custom)
```

Читаемый JSON-снимок справочников и шаблонов:

```
C:\karier\backups\snapshot_before_clean.json
```

Состояние на момент снимка:

| Показатель | Значение |
|---|---|
| Типов оборудования | 18 |
| Объектов (активных) | 585 |
| Объектов всего (с удалёнными) | 4700 |
| Связей | 3788 |
| Шаблонов блоков | 17 |
| Тестов | 144 passed |

**Типы (18):** `ktp`, `substation`, `bkru`, `yaku`, `pump`, `bus_section`, `cell`,
`yaku_1t`, `gen_diesel`, `gen_petrol`, `mast`, `ekg`, `cuckoo`, `bmp`, `pole`, `ksr`,
`dmp`, `dmo`.

**Шаблоны блоков (17):** `substation_35_6`, `bkru_standard`, `ktp_standard`,
`yakno6`, `pktp_63`, `pktp_standard`, `pktp_630`, `yakno1`, `recloser`, `pole`,
`rlnd`, `source_35`, `pktp`, `pktp_04`, `load_04`, `ekg`, `yakno`.

**Принятая схема:** JSON v5 (`seed_data/sketch_v5.json`) принята главным энергетиком;
v6 (`sketch_v6.json`) — полировка неблокирующих замечаний. Скрипты построения:
`seed_schema_blocks.py`, `seed_demo_sketch.py`, `gen_sketch_json.py`.

## 2. Что удалено

```sql
TRUNCATE gis.assets CASCADE;      -- объекты, порты, связи, перемещения, дефекты,
                                  -- документы, фото, обходы (каскадом)
DELETE FROM gis.asset_types;      -- все 18 типов
UPDATE gis.schema_blocks SET is_active = false;  -- шаблоны сохранены, но скрыты
```

После удаления:

| Проверка | Значение |
|---|---|
| `gis.asset_types` | 0 |
| `gis.assets` | 0 |
| `gis.asset_ports` | 0 |
| `gis.links` | 0 |
| `gis.schema_blocks` | 17 (неактивны) |
| `GET /api/asset-types` | `[]` |
| `GET /api/assets` | `total: 0` |
| `GET /api/topology/graph` | 0 узлов, 0 связей |
| `GET /api/schema/blocks` | `[]` (библиотека скрыта) |

Сотрудники, роли, аудит, MCP — не тронуты.

## 3. Как вернуть всё обратно

```powershell
# 1) восстановить базу из дампа
# Пароль karier_user в документации не хранится: он в backend-v2/.env (файл в .gitignore)
$env:PGPASSWORD = (Select-String -Path 'C:\karier\karier\backend-v2\.env' -Pattern '^DATABASE_URL').Line -replace '^.*://[^:]+:([^@]+)@.*$','$1'
& 'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe' `
    -h 127.0.0.1 -U karier_user -d karier_db `
    --clean --if-exists --no-owner `
    'C:\karier\backups\karier_before_clean_20261109.dump'

# 2) перезапустить API
#    (остановить процесс на 8001 и запустить uvicorn заново)
```

`pg_restore` вернёт типы, объекты, связи, шаблоны (с `is_active = true`), историю и фото.

Быстрая альтернатива без восстановления всей истории — заново создать базовые типы:

```powershell
cd C:\karier\backend-v2
.\venv\Scripts\python.exe seed.py
.\venv\Scripts\python.exe seed_schema_blocks.py
```

## 4. Как рисовать вручную

1. Открыть **Типы** (`/types`) — справочник пуст, создать 3–5 нужных типов
   (например, «Ячейка», «Опора», «КТП», «Секция шин»), задать символ на схеме.
2. Открыть **Реестр** (`/registry`) — создать объекты, указать тип и координаты.
3. Открыть **Карта → Схема** (`/map?view=schema`) — включить «Режим редактирования»,
   расставить объекты, соединить порты (линии ортогональные).
4. Библиотека блоков сейчас пуста (шаблоны деактивированы); чтобы вернуть её —
   восстановить дамп или выполнить `seed_schema_blocks.py` после появления типов.

## 5. Важно

* Дамп и JSON лежат вне git (`backups/` в `.gitignore`) — не потеряются при коммитах.
* Перед экспериментами с удалением типов помните: тип нельзя удалить, если на нём есть
  объекты; сейчас объектов нет, поэтому ограничений нет.
* Восстановление дампа затрёт текущее состояние (сейчас оно пустое), это ожидаемо.
