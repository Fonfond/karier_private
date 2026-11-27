# F4: очистка денормализации кабеля при снятии (db_agent)

Дата: 26.11.2026 · проверено на `karier_test_db` · рабочая `karier_db` не менялась
Скоуп: только `karier/backend-v2/app` + этот отчёт. Тесты (tests/) обновляет qa_agent.

## 1. Итог

| Критерий приёмки t6 | Статус | Чем подтверждено |
|---|---|---|
| `POST /api/cables/{id}/return` в `reserve`/`repair` очищает у связи `cable_mark`, `length_m`, `cross_section_mm2` и `cable_asset_id` (NULL) | ✅ | §3: до снятия `cable_asset_id=cable`, `cable_mark=Ф-F4`, `length_m=77.0`, `cross_section_mm2=25.0`; после — все четыре `NULL` |
| `install` по-прежнему заполняет денормализацию и `cable_asset_id`; повторный `return` идемпотентен | ✅ | §3: повторная установка снова заполнила все поля из карточки кабеля; второй `return` → 200, `detached_links=[]`, поля остаются NULL |
| Аудит `cable.returned` фиксирует очистку; старые API не сломаны | ✅ | §2.2 (payload `cleared_fields` + `cleared` с прежними значениями, detail); §4 pytest 22 passed + 48 passed (связи/схема/топология) |
| Регресс-поднабор pytest зелёный; отчёт `docs/team/34b-f4-fix.md` | ✅ | §4: `pytest -q tests/test_stage2_equipment.py tests/test_equipment_fields.py` → **22 passed** |

## 2. Что изменено

Файл: `backend-v2/app/services/cables.py`.

### 2.1 `_detach()` — снятие кабеля со связи

Было (этап 2): очищались только `cable_asset_id`, `cable_status="dismounted"` — марка, длина и
сечение снятого кабеля оставались на связи и продолжали показываться на линии/в отчётах.

Стало:

```python
def _detach(db, cable, link, actor) -> dict[str, Any]:
    cleared = {
        "link_id": str(link.id),
        "cable_asset_id": str(link.cable_asset_id) if link.cable_asset_id else None,
        "cable_mark": link.cable_mark,
        "length_m": float(link.length_m) if link.length_m is not None else None,
        "cross_section_mm2": float(link.cross_section_mm2) if link.cross_section_mm2 is not None else None,
    }
    link.cable_asset_id = None
    link.cable_mark = None
    link.length_m = None
    link.cross_section_mm2 = None
    link.cable_status = "dismounted"
    link.updated_by = actor.id
    link.version = (link.version or 1) + 1
    db.flush()
    return cleared
```

Набор очищаемых полей вынесен в константу `DETACHED_LINK_FIELDS`
(`cable_asset_id`, `cable_mark`, `length_m`, `cross_section_mm2`) — её же использует аудит,
поэтому список в payload и фактическая очистка не разъедутся.

Почему именно эти поля: в `install` (`_denormalize`) связь получает марку/длину/сечение из
карточки кабеля, и после снятия это единственные «параметрические» данные, которые оставались
висеть на линии. `cable_status="dismounted"` остаётся осознанным маркером состояния участка,
`cable_no`/`installed_on` наш `install` не пишет — чистить нечего.

### 2.2 Возврат и аудит

В `return_to_stock()`:

* очистка выполняется только для `reserve`/`repair`; `status="installed"` — это подтверждение
  «кабель установлен», при нём связи и их денормализация сохраняются (как и описано в §4.3
  отчёта этапа 2; раньше реализация расходилась с этим описанием — попутно приведено в соответствие);
* аудит `cable.returned` дополнен (обратная совместимость — прежние ключи сохранены):

```json
{
  "from_status": "installed",
  "to_status": "reserve",
  "links": ["<link uuid>"],
  "reason": "F4: снятие в запас",
  "cleared_fields": ["cable_asset_id", "cable_mark", "length_m", "cross_section_mm2"],
  "cleared": [{"link_id": "<uuid>", "cable_asset_id": "<uuid|null>",
               "cable_mark": "Ф-7К", "length_m": 77.0, "cross_section_mm2": 25.0}]
}
```

`detail` при фактическом снятии содержит «…, очищены cable_mark/length_m/cross_section_mm2 у связи».
При повторном `return` (связей уже нет) — `links: []`, `cleared_fields: []`, `cleared: []`:
аудит не утверждает, что что-то очищено, когда очищать было нечего (идемпотентность).

### 2.3 Установка не менялась

`install` → `_denormalize` заполняет `cable_mark`/`length_m`/`cross_section_mm2` из карточки
кабеля (или явных параметров запроса) и `cable_asset_id`; после `return` повторная установка
снова заполняет все поля (§3). Ответы/схемы API не менялись: `CableOut`, `LinkOut`
(`cable_asset_id`, `cable_asset`) остались как были.

## 3. Ручная проверка сценария (TestClient на `karier_test_db`, созданные объекты удалены)

БКРУ-блок из `POST /api/schema/composite`, кабельная связь ячейка1→ячейка2 (6 кВ), кабель
`Ф-F4` с `length_m=77`, `section_mm2=25`:

| Шаг | `cable_asset_id` | `cable_mark` | `length_m` | `cross_section_mm2` | `cable_status` |
|---|---|---|---|---|---|
| до установки | null | `Ф-F4` (из связи) | null | null | in_work |
| `install {link_id}` → 200 | **cable.id** | `Ф-F4` | **77.0** | **25.0** | in_work |
| `return {reserve}` → 200 | **null** | **null** | **null** | **null** | dismounted |
| повторный `return {reserve}` → 200 | null | null | null | null | dismounted |
| `install {link_id}` (повторно) → 200 | **cable.id** | `Ф-F4` | **77.0** | **25.0** | in_work |
| `return {repair}` → 200 | **null** | **null** | **null** | **null** | dismounted |
| `return {installed}` (подтверждение) | cable.id | `Ф-F4` | 77.0 | 25.0 | in_work |
| `install {asset_id}` (на ячейку без свободной связи) | — | — | — | — | — (200, `installed_on=CELL-317`) |

Аудит после первого `return` (фактическая строка `audit.audit_log`):

```json
{"links": ["0a229703-…"], "reason": "F4: снятие в запас",
 "cleared": [{"link_id": "0a229703-…", "cable_asset_id": "f4d482e2-…",
              "cable_mark": "Ф-F4", "length_m": 77.0, "cross_section_mm2": 25.0}],
 "to_status": "reserve", "from_status": "installed",
 "cleared_fields": ["cable_asset_id", "cable_mark", "length_m", "cross_section_mm2"]}
```

Повторный `return` — `cleared: []` (см. §2.2). Установка «на объект» и невалидные статусы
(`422`) не менялись.

## 4. Регресс

| Команда | Результат |
|---|---|
| `pytest -q tests/test_stage2_equipment.py tests/test_equipment_fields.py` (контракт t6) | **22 passed**, 536 warnings in 22.19s |
| `pytest -q tests/test_line_builder.py tests/test_schema_builder.py tests/test_gis_api.py tests/test_sprint12_api.py tests/test_topology_api.py` | **48 passed**, 543 warnings in 102.39s |

`tests/test_stage2_equipment.py` (написан qa_agent) сейчас проверяет после `return` только
`cable_asset_id is None` и `cable_status="dismounted"` — эти проверки по-прежнему зелёные.
Ассерты на очистку `cable_mark/length_m/cross_section_mm2` и на `cleared_fields` в аудите
добавит qa_agent (tests/ вне моего скоупа); контракт для них — §2.2/§3.

## 5. Файлы и хеши (SHA-256, от `C:\karier\karier`)

| Файл | Размер | SHA-256 |
|---|---|---|
| `backend-v2/app/services/cables.py` | 19310 | `46ddc79e8be47151a3f9f688ee8bb8d8c6816dbf553dc79042a9cab34bfde035` |

Не менялись: `backend-v2/tests`, `karier/src-v2`, `backend-v2/.env`, миграции, схемы/роутеры
(`_detach` — внутренняя функция сервиса). Рабочая `karier_db` не затрагивалась.

## 6. Для qa_agent: что проверять в F4

1. `install {link_id}` → `_link_row` заполнены `cable_asset_id`, `cable_mark`, `length_m`,
   `cross_section_mm2` (выше — как было в этапе 2).
2. `return {reserve|repair}` → все четыре поля у связи **NULL**, `cable_status="dismounted"`,
   аудит `cable.returned` с `cleared_fields` и прежними значениями в `cleared`.
3. Повторный `return` → 200, `detached_links=[]`, поля остаются NULL, аудит `cleared=[]`.
4. Повторный `install` → денормализация снова заполнена из карточки кабеля.
5. `return {status:"installed"}` — подтверждение: связь не рвётся, поля остаются.
