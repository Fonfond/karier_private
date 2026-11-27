# F4: тесты очистки кабельной денормализации при снятии (qa_agent)

Дата: 26.11.2026 · тестовая БД `karier_test_db` (ревизия `0016_stage2_equipment`)
Задача: t7 — закрепить тестами исправление F4 (t6): `POST /api/cables/{id}/return` очищает
у связи `cable_asset_id`, `cable_mark`, `length_m`, `cross_section_mm2`, аудит
`cable.returned` фиксирует очистку, повторный `return` идемпотентен.
Скоуп: только `backend-v2/tests` + этот отчёт. `backend-v2/app` и `src-v2` **не менялись**
(хеши `cables.py`/`state.py` совпадают с t6/этапом 2).

## 1. Итог

| Критерий приёмки t7 | Статус | Чем подтверждено |
|---|---|---|
| Тест: после `install` кабель заполняет `cable_mark`/`length_m`/`cross_section_mm2` и `cable_asset_id`; после `return` — все четыре поля NULL/пустые, `cable_status` = `reserve` (или `repair`) | ✅ | `test_cable_return_clears_denormalization_and_audit`: после install — `cable_asset_id=cable.id`, `cable_mark=Ф-…`, `length_m=120.0`, `cross_section_mm2=35.0`, `link.cable_status='in_work'`; после return в запас — все четыре `None`, `link.cable_status='dismounted'`, `cable.lifecycle_status='reserve'`; после return в ремонт — снова все `None`, `cable.lifecycle_status='repair'`. Так же усилен `test_cable_install_return_reserve_and_repair` |
| Тест: повторный `return` идемпотентен, аудит `cable.returned` есть | ✅ | Тот же тест: второй `return {reserve}` → 200, `detached_links=[]`, поля остаются `None`, `version` связи не меняется; аудит: `links=[]`, `cleared_fields=[]`, `cleared=[]`. Первый возврат — аудит с `from_status=installed→to_status=reserve`, `links=[link]`, `cleared_fields` (4 поля), `cleared[0]` с прежними значениями (`cable_mark`, 120.0, 35.0, `cable_asset_id`), `detail` содержит «очищены cable_mark/length_m/cross_section_mm2» |
| Тест: toggle из API по-прежнему возвращает `voltage`/`energized` (регресс F1 не затрагивает backend) | ✅ | `test_toggle_cell_returns_status_energized_voltage` и `test_toggle_grounded_cell_is_not_energized` — зелёные в полном прогоне: on → `energized=true`, `voltage_kv=6.0`, off → `false/0.0`, заземление → `energized=false`; `app/services/state.py` не менялся (SHA-256 `131256c2…`, как в этапе 2) |
| Новые тесты добавлены в `backend-v2/tests`; полный `pytest -q`: 0 failed, passed зафиксирован; отчёт | ✅ | `tests/test_stage2_equipment.py`: **13 passed** (12 + 1 новый); полный `pytest -q`: **227 passed, 3 skipped, 0 failed**, exit 0, 320.63 с (лог `backend-v2/var/qa_t7_full_pytest.log`) |

## 2. Что изменено в тестах

Файл: `backend-v2/tests/test_stage2_equipment.py` (было 12 тестов, стало 13).

### 2.1 Новый тест `test_cable_return_clears_denormalization_and_audit`

Полный цикл F4 на свежесозданном БКРУ-блоке (свои ячейки, своя кабельная связь, свой кабель
`reserve` с `cable_mark`, `length_m=120`, `section_mm2=35`):

1. `install {link_id}` → у связи `cable_asset_id`, `cable_mark`, `length_m=120.0`,
   `cross_section_mm2=35.0`, `cable_status='in_work'`;
2. `return {status:"reserve", reason}` → 200, `detached_links=[link]`, кабель
   `lifecycle_status='reserve'`; у связи **все четыре поля `None`**, `cable_status='dismounted'`
   (версия связи запоминается — по ней проверяется идемпотентность шага 4);
3. аудит `cable.returned`: `from_status=installed`, `to_status=reserve`, `links=[link]`,
   `reason`, `cleared_fields=["cable_asset_id","cable_mark","length_m","cross_section_mm2"]`,
   `cleared=[{link_id, cable_asset_id, cable_mark, length_m:120.0, cross_section_mm2:35.0}]`,
   актор `000001`, `detail` содержит «очищены cable_mark/length_m/cross_section_mm2»;
4. повторный `return {reserve}` → 200, `detached_links=[]`, кабель остаётся `reserve`, поля
   `None`, `version` связи **не изменился** (идемпотентность); аудит: `links=[]`,
   `cleared_fields=[]`, `cleared=[]` — журнал не утверждает, что что-то очищено;
5. повторный `install {link_id}` → денормализация снова заполнена из карточки кабеля
   (`cable_asset_id`, марка, 120.0, 35.0, `in_work`);
6. `return {status:"installed"}` — это подтверждение установки, а не снятие: 200,
   `detached_links=[]`, связь и все четыре поля сохранены, аудит `to_status=installed`,
   `links=[]`, `cleared_fields=[]`;
7. `return {status:"repair"}` → 200, `detached_links=[link]`, кабель `repair`, все четыре поля
   `None`, `cable_status='dismounted'`; аудит `to_status=repair` с `cleared_fields` (4 поля) и
   прежней маркой в `cleared`.

Терминология в отчёте: `cable_status` из критерия — это состояние **кабеля**
(`cable.lifecycle_status = reserve|repair`); у **связи** после снятия осознанно остаётся
`cable_status='dismounted'` (маркер «участок без кабеля») — тест проверяет оба поля, чтобы
не спутать их в будущем.

### 2.2 Усилен существующий `test_cable_install_return_reserve_and_repair`

Добавлены проверки F4 в уже существующие шаги:

* после первого `return` в запас — `cable_mark`/`length_m`/`cross_section_mm2` тоже `None`
  (раньше проверялся только `cable_asset_id`);
* после повторной установки — денормализация восстановлена (все четыре поля);
* после `return` в ремонт — все четыре поля снова `None`.

Это закрывает чек-лист t6 §6 (пп. 1–4) в общем сценарии; новый тест дополнительно проверяет
идемпотентность, аудит `cleared*` и подтверждение `status="installed"` (п. 5 чек-листа).

### 2.3 Регресс F1 (frontend) не затрагивает backend

F1 исправлялся только во фронтенде (t5: `AssetSheet.onStateChanged` → `MapPage`), backend
`toggle` не менялся: `app/services/state.py` SHA-256 `131256c2…` совпадает с этапом 2.
Тесты toggle в `test_stage2_equipment.py` остались зелёными в полном прогоне (см. §1),
API-ответ `{status, energized, voltage_kv, grounded}` не изменился.

## 3. Прогоны

| Команда | Результат |
|---|---|
| `pytest -q tests/test_stage2_equipment.py` | **13 passed**, exit 0, 16.30 с |
| `pytest -q` (полный, финальный) | **227 passed, 3 skipped, 0 failed**, exit 0, 320.63 с (0:05:20), 639 warnings |

Пропуски (3) — прежние `tests/test_migrations.py` (`test_single_alembic_head`,
`test_upgrade_downgrade_upgrade`, `test_autogenerate_has_only_known_drift`): нужна отдельная
БД в `TEST_MIGRATION_DATABASE_URL`, на стенде переменная не задана (см. `33d-stage2-acceptance.md` §9 F5).
Лог полного прогона: `backend-v2/var/qa_t7_full_pytest.log`.

Состояние `karier_test_db` после прогона: ревизия `0016_stage2_equipment`, `gis.assets`
5049 (585 активных), `gis.links` 3788 (3737 активных), `links.cable_asset_id IS NOT NULL` — 0
(изоляция `tests/conftest.py` работает, мусора от тестов нет).

## 4. Фактический аудит `cable.returned` (строка из тестовой БД)

Тесты проверяют не мок, а реальные строки `audit.audit_log`. Пример из прогона (три последних
события цикла: повторное снятие → подтверждение → снятие в ремонт; UUID сокращены для читаемости):

```json
{"actor": "000001", "role": "admin",
 "detail": "Кабель CABLE-4: reserve → reserve (причина: F4: повторное снятие)",
 "payload": {"from_status": "reserve", "to_status": "reserve", "links": [],
             "reason": "F4: повторное снятие", "cleared_fields": [], "cleared": []}}

{"actor": "000001", "role": "admin",
 "detail": "Кабель CABLE-4: installed → installed (причина: F4: подтверждение)",
 "payload": {"from_status": "installed", "to_status": "installed", "links": [],
             "reason": "F4: подтверждение", "cleared_fields": [], "cleared": []}}

{"actor": "000001", "role": "admin",
 "detail": "Кабель CABLE-4: installed → repair, снят со связей: 1, очищены cable_mark/length_m/cross_section_mm2 у связи (причина: F4: в ремонт)",
 "payload": {"from_status": "installed", "to_status": "repair",
             "links": ["81eba6fa-…"],
             "reason": "F4: в ремонт",
             "cleared_fields": ["cable_asset_id", "cable_mark", "length_m", "cross_section_mm2"],
             "cleared": [{"link_id": "81eba6fa-…", "cable_asset_id": "b58365b9-…",
                          "cable_mark": "Ф-0ADBCC", "length_m": 120.0,
                          "cross_section_mm2": 35.0}]}}
```

Прежние ключи (`from_status`/`to_status`/`links`/`reason`) сохранены — обратная совместимость
с потребителями аудита; новые ключи (`cleared_fields`, `cleared`) только добавляют данные.

## 5. Файлы и хеши (SHA-256, от `C:\karier\karier`)

Определение агрегатов — как в `33c-stage2-tests.md`/`33d-stage2-acceptance.md`: SHA-256 от строк
`"<sha256>  <путь>"` (POSIX-путь), отсортированных по пути, `\n` после каждой; только `*.py`.

| Область | Файлов | Агрегат SHA-256 |
|---|---:|---|
| `backend-v2/app` | 80 | `9999cfd4fc355d98af2745207da6559f6147779e7b0fc202558a65528265a0be` |
| `backend-v2/tests` | 34 | `d528029ab937f06f14f84390f491e93a72b61eadd7186375734e1bb77880954f` |

| Файл | Размер | SHA-256 |
|---|---:|---|
| `backend-v2/tests/test_stage2_equipment.py` (**изменён**: 12 → 13 тестов) | 52789 | `6151871de35c4ecf235e41121687b17192759842838e361e3c5dbfcd37d60a89` |
| `backend-v2/tests/conftest.py` (не менялся) | 13029 | `40b99ab45351011599251baa2dee6bcde37fcb47dfd1caad9c6522eb0453ccc9` |
| `backend-v2/app/services/cables.py` (правка F4, t6; **не менялся в t7**) | 19310 | `46ddc79e8be47151a3f9f688ee8bb8d8c6816dbf553dc79042a9cab34bfde035` |
| `backend-v2/app/services/state.py` (toggle; не менялся) | 9976 | `131256c20c43d51a650fe2a0bfa8ac0de3709e9f1fb702085dd643cc9fb7a1fc` |

Агрегат `app/` изменился относительно `33c/33d` только из-за правки `cables.py` в t6
(`46ddc79e…` — ровно хеш из отчёта t6 `34b-f4-fix.md`); `state.py` и остальные файлы этапа 2
не менялись. В t7 менялся только тестовый файл.

Рабочая `karier_db` на момент этой задачи: head `0016_stage2_equipment`, тип `razedinitel` есть,
25 комплектных типов, `links.cable_asset_id` есть — **эта задача миграций не запускала**
(t7 только читал БД read-only; на момент приёмки t4 рабочая БД была на `0015`). Изменение
относится к отдельным работам по выпуску F4, не к t7; рабочая БД не трогалась ни одним
шагом этой задачи.

## 6. Для приёмки: что теперь зафиксировано тестами

1. `install` заполняет `cable_asset_id` + `cable_mark`/`length_m`/`cross_section_mm2`
   (в т.ч. повторный install после снятия).
2. `return {reserve|repair}` очищает все четыре поля у связи, `link.cable_status='dismounted'`,
   `cable.lifecycle_status` = `reserve`/`repair`; аудит `cable.returned` содержит
   `cleared_fields` и прежние значения в `cleared` + человекочитаемый `detail`.
3. Повторный `return` идемпотентен (200, `detached_links=[]`, `version` связи не меняется,
   `cleared=[]`).
4. `return {status:"installed"}` — подтверждение: связь и денормализация сохраняются.
5. Toggle-API не затронут: `voltage_kv`/`energized` по-прежнему возвращаются (регресс F1 — только UI).

## 7. Воспроизведение

```powershell
cd C:\karier\karier\backend-v2
.\venv\Scripts\python.exe -m pytest -q tests/test_stage2_equipment.py   # 13 passed
.\venv\Scripts\python.exe -m pytest -q                                 # 227 passed, 3 skipped
```

Тесты используют только `karier_test_db` (guard в `tests/conftest.py`), созданные объекты
убирает `isolate_created_rows`; аудит append-only — строки `cable.returned` остаются (это
штатное поведение журнала и использовано как доказательство в §4).

## 8. Границы

* `backend-v2/app` и `src-v2` не менялись; правка `cables.py` — из t6 (`46ddc79e…`);
* рабочая `karier_db` этой задачей не менялась (миграции/записи не запускались);
* изменён только `backend-v2/tests/test_stage2_equipment.py` (+ этот отчёт);
* не проверялось: полный цикл миграций на отдельной БД (нет `TEST_MIGRATION_DATABASE_URL`),
  UI-поведение F4 (снятие кабеля в браузере — вне t7; F1-фикс проверен в t5).
