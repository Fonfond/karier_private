# Этап 2 модели оборудования «Карьер»: тесты шаблонов, переключения и кабелей (qa_agent)

Дата: 26.11.2026 · тестовая БД `karier_test_db` (ревизия `0016_stage2_equipment`)
Рабочая БД `karier_db` **не менялась** (read-only проверка: head `0015_asset_type_fields`,
колонки `gis.links.cable_asset_id` нет, типа `razedinitel` нет, 12 объектов).
Файлы приложения (`backend-v2/app`, `backend-v2/alembic`) и фронтенд (`src-v2`) qa_agent
**не менял** — хеши `app/` совпадают с отчётом t1 `33a-db-stage2.md` (§7).

## 1. Итог

| Требование контракта t3 | Статус | Чем подтверждено |
|---|---|---|
| Тест: `POST /api/schema/composite` для БКРУ → ровно 6 ячеек, `cell_kind` `[in,out,out,sectional,out,in]`, `section_no` `[1,1,1,1,2,2]`, номера 1…6 | ✅ | `test_composite_bkru_exactly_six_cells_with_layout` — API-ответ + строки БД (`schema_role`, `parent_asset_id`, раскладка 60/140 + 120×96); аудит `composite.composed` (6 ячеек, 2 секции, актор `000001`) |
| Тест: ПС 35/6 по умолчанию 17 ячеек на секцию (15 `out` + 1 `in` + 1 `sectional`) и 34 всего; параметр `cells_per_section`; недопустимое значение → 422 | ✅ | `test_composite_ps_default_17_cells_per_section`, `test_composite_ps_cells_per_section_parameter` (n=3, 5, 10), `test_composite_invalid_cells_per_section_rejected` (0/±/51 → 422, «полублоков» нет; БКРУ/КТП + параметр → 422 `composite.not_configurable`) |
| Тест: КТП → 0 ячеек, создан дочерний разъединитель (`cell_kind=in`), он переключается | ✅ | `test_composite_ktp_has_no_cells_but_toggleable_disconnector` — `cells=[]`, `children=1`, тип `razedinitel`/класс `switching`, затем `toggle` on/off (6 кВ → 0 кВ) |
| Тесты toggle: меняет on/off, возвращает `status/energized/voltage_kv/grounded`; `audit.audit_log` с актором и прежним/новым состоянием; без права `asset.status.edit` → 403; не-ячейка/не-разъединитель → 400 | ✅ (с оговоркой §6.1: фактически 422) | `test_toggle_cell_returns_status_energized_voltage`, `test_toggle_grounded_cell_is_not_energized`, `test_toggle_writes_audit_with_actor_and_previous_new_state` (строка `asset.toggled` + `gis.switching_ops`), `test_toggle_requires_asset_status_edit_permission` (viewer 403 + оператор 200), `test_toggle_rejects_asset_that_is_not_cell_or_switching` (422 `asset.not_switchable`, 404, 422 `validation.failed`) |
| Тесты кабелей: install → `installed` и `links.cable_asset_id`; return → `reserve`; repair; невалидный переход/статус → 422; аудит | ✅ (конфликты переходов — 409, §6.3) | `test_cable_install_return_reserve_and_repair` (install на связь и «на объект», return reserve/repair, `links.cable_asset_id`, аудит `cable.installed`/`cable.returned`), `test_cable_invalid_statuses_and_install_conflicts` (422 статусы/фильтр, 409 `cable.already_installed`/`cable.link_occupied`, 422 `cable.not_cable`, 403) |
| Полный `pytest -q` на `karier_test_db`: 0 failed, passed зафиксирован | ✅ | **226 passed, 3 skipped, 0 failed** (303.79 с, exit 0), лог `backend-v2/var/qa_stage2_full_pytest.log` |
| Отчёт `docs/team/33c-stage2-tests.md` с хешами `app/` и `tests/` | ✅ | этот документ, §7 + приложение A (полный манифест 114 файлов `*.py`) |

## 2. Файл тестов

`backend-v2/tests/test_stage2_equipment.py` — **12 тестов** (986 строк), новый файл,
запускается на изолированной `karier_test_db` (см. `tests/conftest.py`: подмена DSN до
импорта приложения, fail-fast при не-тестовой БД, `heal_topology` + `isolate_created_rows`).

| # | Тест | Что закрепляет |
|---|---|---|
| 1 | `test_composite_bkru_exactly_six_cells_with_layout` | 6 ячеек, `cell_kind`, сквозные номера 1…6, секции 1/2 (4+2), имена, `schema_role`, координаты раскладки, дочерность в БД, аудит создания |
| 2 | `test_composite_ps_default_17_cells_per_section` | 2×17=34; состав секции 1 `in` + 15 `out` + 1 `sectional`; порядок; 35/6 кВ; `cell_no` 1…34; `attrs.cells_per_section=17` |
| 3 | `test_composite_ps_cells_per_section_parameter` | n=3 → 1 `out` + 2 служебных (3 на секцию, 6 всего); n=5 → 3 `out` + 2 служебных; n=10 → 20; `attrs.cells_per_section` в карточке блока |
| 4 | `test_composite_invalid_cells_per_section_rejected` | 0/51/−1 → 422 `validation.failed` (поле `cells_per_section`), ни одной созданной строки; БКРУ/КТП + параметр → 422 `composite.not_configurable` |
| 5 | `test_composite_ktp_has_no_cells_but_toggleable_disconnector` | КТП: 0 ячеек, 1 дочерний разъединитель (`cell_kind=in`, `switching`, 6 кВ), его `toggle` on/off, аудит `composite.composed` |
| 6 | `test_toggle_cell_returns_status_energized_voltage` | on → `energized=true/voltage_kv=6.0`, off → `false/0.0`; `previous_status`, `changed`, `version`, карточка; без тела — «переключить»; повтор состояния → `changed=false` |
| 7 | `test_toggle_grounded_cell_is_not_energized` | заземление (`/state`) + `status=on` → `energized=false`, `voltage_kv=0`, `grounded=true` (зелёный цвет по контракту UI) |
| 8 | `test_toggle_writes_audit_with_actor_and_previous_new_state` | `audit.audit_log`: `asset.toggled`, актор `000001`/`admin`, `detail "…: off → on"`, `payload.from_state/to_state` (+`from`/`to`), `reason`, `energized`, `voltage_kv`, `grounded`, `cell_kind`; запись `gis.switching_ops` (`status_on`, from/to, performed_by); вторая строка для on→off |
| 9 | `test_toggle_requires_asset_status_edit_permission` | viewer → 403 `perm.denied`, состояние не меняется, отказ в аудите с актором; оператор (`asset.status.edit` есть) → 200 и своя запись аудита |
| 10 | `test_toggle_rejects_asset_that_is_not_cell_or_switching` | опора и сам блок КТП → 422 `asset.not_switchable` (объект не меняется); несуществующий id → 404; `state="standby"` → 422 `validation.failed` |
| 11 | `test_cable_install_return_reserve_and_repair` | reserve → install на связь (`links.cable_asset_id`, `cable_status=in_work`, денормализация марки/длины/сечения, `installed_on`), список `installed`; return → `reserve` (`detached_links`, `cable_asset_id=NULL`, `dismounted`); повторный install → return `repair`; install `{"asset_id":…}` → «на объекте» (`attrs.installed_on_asset_id`); аудит `cable.installed`/`cable.returned` с актором |
| 12 | `test_cable_invalid_statuses_and_install_conflicts` | `?lifecycle_status=bogus` → 422; return `{"status":"bogus"}` → 422; install без цели → 422; не-кабель → 422 `cable.not_cable`; уже установлен → 409 `cable.already_installed`; связь занята → 409 `cable.link_occupied`; viewer на install/return → 403 |

Принципы, чтобы тесты не зависели от остатков прошлых прогонов:

* составные устройства создаются «с нуля» под уникальными кодами (`QA-<ТИП>-<8 hex>`),
  seeded-объекты и шаблоны типов не правятся;
* аудит проверяется **по строкам `audit.audit_log`** (актор, `entity_id`, payload), а не по
  мокам: журнал пишется middleware после ответа, тест читает его отдельной сессией;
* созданные объекты/связи/сотрудники убирает `isolate_created_rows`; после прогона
  `karier_test_db` вернулась к baseline: **585 объектов / 3737 связей / 20 типов**,
  `links.cable_asset_id IS NOT NULL` — 0, объектов `CABLE-%` — 0 (журнал аудита append-only,
  поэтому строки `cable.*`/`asset.toggled` остаются — так и задумано).

## 3. Прогоны

Выполнялось по одному pytest за раз на `karier_test_db` (без параллельных прогонов).

| Команда | Результат |
|---|---|
| `.\venv\Scripts\python.exe -m pytest -q tests/test_stage2_equipment.py` | **12 passed**, exit 0, 13.75 с |
| `.\venv\Scripts\python.exe -m pytest -q` (полный, финальный) | **226 passed, 3 skipped, 0 failed**, exit 0, 303.79 с (0:05:03), 638 warnings |

Пропуски (3) — `tests/test_migrations.py::test_single_alembic_head`,
`::test_upgrade_downgrade_upgrade`, `::test_autogenerate_has_only_known_drift`: они требуют
отдельную БД в `TEST_MIGRATION_DATABASE_URL` (цикл `downgrade base` уничтожает таблицы);
переменная в этом окружении не задана, у роли `karier_user` нет права `CREATEDB`.
Подробности — в `33a-db-stage2.md` §3; полный цикл миграций проверял db_agent на
`karier_test_db` head→down→up со сверкой md5.

Полный лог: `backend-v2/var/qa_stage2_full_pytest.log` (вне `docs/`, каталог `var/`).

## 4. Что именно проверяется в аудите и журналах

Тесты читают БД напрямую (не моки):

* `audit.audit_log`, `action='asset.toggled'`, `entity='asset'`, `entity_id=<ячейка>`, `result='ok'`:
  `actor_id` = id администратора `000001`, `actor_tab_no='000001'`, `actor_role='admin'`,
  `detail = "<CODE>: off → on"` (+ причина), `payload` содержит `from_state`, `to_state`,
  алиасы `from`/`to`, `reason`, `energized`, `voltage_kv`, `grounded`, `cell_kind`, `changed`;
* `gis.switching_ops`: `action='status_on'|'status_off'`, `from_state`, `to_state`, `reason`,
  `performed_by` = актор (совместимо с журналом Спринта 4);
* отказ по правам: `audit.audit_log`, `action='perm.denied'`, `result='denied'`, `actor_id` = viewer;
* `audit.audit_log`, `action='cable.installed'` / `'cable.returned'`: `payload.from_status`,
  `to_status`, `link_id`/`asset_id`, `links` (снятые связи), `reason`, актор;
* `audit.audit_log`, `action='composite.composed'`: `payload.type_code`, список id ячеек,
  число секций, `disconnector_id`, `cells_per_section`.

## 5. Найдено и устранено: порча seeded-связей в `karier_test_db` (важно для приёмки)

### 5.1 Симптом

Первый полный прогон (до правки данных) дал **1 failed, 225 passed, 3 skipped**:
`tests/test_topology_api.py::test_power_path_full_chain` — в цепочке питания КТП-14
ожидалась подпись связи `СБ-3×50`, фактически среди подписей была `Ф-7К`
(`['ф.21К', 'ф.21К', 'Шина БКРУ', 'АВБбШв 4×35', 'Ф-7К']`).
Тот же тест падал **изолированно** (`pytest -q tests/test_topology_api.py::test_power_path_full_chain`
→ 1 failed за 1.5 с), то есть это не следствие моих тестов и не зависимость от порядка.

### 5.2 Причина (по журналу аудита, не догадка)

В UI-E2E проверке кабельного учёта (ui_agent, t2) демо-кабель «Ф-7К»
(`cable_id 15c90e6f-7e0f-4d90-a420-940727791c52`, attrs: марка `Ф-7К`, длина 120 м,
сечение 35 мм²) ставился на **seeded-связи**, и после удаления демо-кабеля на связях осталась
денормализация `cable_mark = 'Ф-7К'`, `length_m = 120`, `cross_section_mm2 = 35`,
`cable_status = 'dismounted'` (`cable_asset_id` обнулился по `ON DELETE SET NULL`).
Строки `audit.audit_log` (`action='cable.installed'`, актор `000001`, `reason='UI test'`):

| Когда (+08) | link_id | Связь | Было |
|---|---|---|---|
| 2026-11-26 20:10:00 | `e0089dd9-a2a1-42fb-a21f-4cb58983d7c8` | `POLE-2 → POLE-3` (ВЛ-6кВ-4) | `installed` (кабель уже стоял) |
| 2026-11-26 20:45:38 | `1dc47bd1-05e1-4b66-bc89-c4aef08b3224` | `KTP-15 → DMP-2` | `reserve → installed` |
| 2026-11-26 20:50:15 | `8eec8b06-eb3f-457a-bda4-cf762dea9019` | `BKRU1-OUT1 → KTP-14` | `reserve → installed` |

До порчи эти связи имели seed-значения (видно и по журналу: `link.state_changed`
«Связь СБ-3×50…», «Связь КГ-3×25…», «Связь ВЛ-6кВ-4…»), и соседние seeded-связи
(`BKRU1-OUT2→KTP-15` `СБ-3×50`/210, `BKRU1-OUT3→KS-3` `СБ-3×35`/150) остались целы.
`backend-v2/app` qa_agent не менял — хеши совпадают с `33a-db-stage2.md` §7
(`equipment_templates.py b4584e75…`, `state.py 131256c2…`, `cables.py 0163d22f…` и т. д.).

### 5.3 Восстановление baseline (только тестовая БД)

Три связи возвращены к значениям `backend-v2/seed_topology.py` (единственный источник
правды для этих строк; `cable_asset_id` уже был NULL):

| Связь | До восстановления | После (baseline seed) |
|---|---|---|
| `BKRU1-OUT1 → KTP-14` | `Ф-7К` / 120 м / 35 мм² / dismounted | **`СБ-3×50` / 180 м / — / `in_work`** |
| `POLE-2 → POLE-3` | `Ф-7К` / 120 / 35 / dismounted | **`АС-70` / 48 м / — / `in_work`** |
| `KTP-15 → DMP-2` | `Ф-7К` / 120 / 35 / dismounted | **`КГ-3×25` / 70 м / — / `in_work`** |

```sql
-- восстановление seed-денормализации трёх связей (karier_test_db)
update gis.links set cable_mark='СБ-3×50', length_m=180, cross_section_mm2=NULL,
       cable_status='in_work', state='connected'
 where id='8eec8b06-eb3f-457a-bda4-cf762dea9019';  -- BKRU1-OUT1 -> KTP-14
update gis.links set cable_mark='АС-70',   length_m=48,  cross_section_mm2=NULL,
       cable_status='in_work', state='connected'
 where id='e0089dd9-a2a1-42fb-a21f-4cb58983d7c8';  -- POLE-2 -> POLE-3
update gis.links set cable_mark='КГ-3×25', length_m=70,  cross_section_mm2=NULL,
       cable_status='in_work', state='connected'
 where id='1dc47bd1-05e1-4b66-bc89-c4aef08b3224';  -- KTP-15 -> DMP-2
```

После восстановления: `pytest -q tests/test_topology_api.py` → **13 passed**; полный
прогон → **226 passed, 0 failed**. Ни тесты, ни приложение под этот симптом не правились.

### 5.4 Выводы и рекомендации

1. Ручные/E2E-проверки кабельного учёта нужно делать **на своих связях** (создать связь
   между тестовыми ячейками, как в t3), а не на seeded (`BKRU1-OUT1→KTP-14` и т. п.):
   установка кабеля перезаписывает денормализацию связи, а снятие/удаление кабеля её не
   восстанавливает.
2. Продуктовый вопрос вне t2/t3: должен ли `/return` (и `ON DELETE SET NULL` кабеля)
   очищать/восстанавливать `link.cable_mark/length_m/cross_section_mm2`? Сейчас по контракту
   t1 §4.3 снятие только ставит `cable_status='dismounted'` — этого достаточно для учёта, но
   seeded-денормализация остаётся «от снятого кабеля». Предлагаю отдельную задачу, если
   нужна чистота полей связи.
3. Полезен идемпотентный `seed`/reset-скрипт для `karier_test_db`, который возвращает
   seeded-связи к `seed_topology.LINKS` (сейчас такого нет; приёмке стоит знать).
4. Замечена старая (2026-11-09) дрейф-строка, не влияющая на прогон и **не тронутая**:
   `BKRU-1 → BKRU1-OUT1` (busbar) имеет `cable_mark='АВБбШв 4×35'`, `length_m=123.4` вместо
   seed `'Шина БКРУ'`/3 — след `PATCH /api/links` (тест `test_sprint12_api.py`), который
   восстанавливает поля, но однажды не восстановил. Ни один тест от этой подписи не зависит.

## 6. Расхождения формулировок контракта t3 с фактическим API (для приёмки)

Тесты фиксируют **фактическое поведение**, задокументированное в t1 (`33a-db-stage2.md`) и
подтверждённое живыми вызовами; `backend-v2/app` вне зоны t3, поэтому код не менялся.

### 6.1 «не-ячейка/не-разъединитель → 400» — фактически 422

`state_service._require_toggleable` отдаёт `ApiError(422, "asset.not_switchable", …)`
(так же в контракте t1 §4.2 и в §5.5 отчёта t1: `POST /api/assets/{pole}/toggle → 422`).
Тест `test_toggle_rejects_asset_that_is_not_cell_or_switching` закрепляет 422 и проверяет,
что объект не изменился. Обе формулировки — клиентская ошибка 4xx; если приёмке нужен
именно 400, это отдельное изменение `app/services/state.py` + правка теста.

### 6.2 «`cells_per_section=3` даёт 3 отходящих + 2 служебных»

По контракту t1 §4.1 `cells_per_section` — число ячеек **всей секции**, и по умолчанию
17 = 1 `in` + 15 `out` + 1 `sectional` (формула `1 in + (n−2) out + 1 sectional`). Поэтому:
* `n=3` → 1 отходящая + 2 служебных (3 на секцию, 6 всего);
* «3 отходящих + 2 служебных» (5 на секцию) получаются при **n=5**.

Тест `test_composite_ps_cells_per_section_parameter` проверяет оба случая (n=3, 5, 10) —
какая бы трактовка ни имелась в виду, число ячеек зафиксировано.

### 6.3 «невалидный переход/статус → 422»

422 — для невалидных **значений** (`?lifecycle_status=bogus`, `return {"status":"bogus"}`,
install без цели, не-кабель). Конфликты **переходов** отдают 409 с отдельными кодами:
`cable.already_installed`, `cable.link_occupied` (контракт t1 §4.3); тест
`test_cable_invalid_statuses_and_install_conflicts` закрепляет и 422, и 409.

## 7. Хеши (SHA-256, от `C:\karier\karier`)

Определение агрегата: SHA-256 от строк `"<sha256>  <путь>"` (два пробела, путь относительно
`C:\karier\karier`, POSIX), отсортированных по пути, с `\n` после каждой строки; только `*.py`.

| Область | Файлов | Агрегат SHA-256 |
|---|---:|---|
| `backend-v2/app` | 80 | `db5ce3e4f8b3bb6b56be21eaff93339093b917bce3fdefe2e23dc5c45ce98cdc` |
| `backend-v2/tests` | 34 | `5e408c82be4ee22b1a16d2fc90e7d04bc4b67a576ee2670bbdcfe61635d101a7` |

Ключевые файлы:

| Файл | Размер | SHA-256 |
|---|---:|---|
| `backend-v2/tests/test_stage2_equipment.py` (**новый**) | 44155 | `7f371e5d91ecdc66802401d414565f844ab2fbef5130a12496cc41e20dfa521a` |
| `backend-v2/tests/conftest.py` (не менялся) | 13029 | `40b99ab45351011599251baa2dee6bcde37fcb47dfd1caad9c6522eb0453ccc9` |
| `backend-v2/app/services/equipment_templates.py` | 24833 | `b4584e7553b56c575280a30214e7dd23a5d6fbc92f2326ad7abc69ca808cd89a` |
| `backend-v2/app/services/composite.py` | 15270 | `cc1ad97f503a501f965e9673d5137dc34d70c11cfc8dd4c9931040354faaf963` |
| `backend-v2/app/services/state.py` | 9976 | `131256c20c43d51a650fe2a0bfa8ac0de3709e9f1fb702085dd643cc9fb7a1fc` |
| `backend-v2/app/services/cables.py` | 16790 | `0163d22f80d6c524428438ee06c0aa999808dd7988d4c405a491402e3cc249f7` |
| `backend-v2/app/services/gis.py` | 37090 | `aa767b923f32d8d07a2d2c90a2fac9fc0868766dcc541bdfa8cbc97c57aca990` |
| `backend-v2/app/services/links.py` | 11635 | `6d39ff50b3621cfbd43ce143692531dec5ad4354767f9f4feb6a5f781e5ebe53` |
| `backend-v2/app/models/topology.py` | 7628 | `25a6a90a95e11a09f4ceb8248bf53bf588873099e4a885534568c43f2e202546` |
| `backend-v2/app/schemas/equipment.py` | 6070 | `9db2e4089bee1360068acc0dee32b8d82f52d8adcac7c589139aa1374d66f561` |
| `backend-v2/app/schemas/gis.py` | 28405 | `e4781d65243c9bf514baa5992943114ed9f248d7f0f0f0106766a0db27e464dd` |
| `backend-v2/app/api/routers/schema_blocks.py` | 16452 | `ea1ab16aa696cd67e9b4cf64ce487c4378e547ee080d40432b4680621a83f7d2` |
| `backend-v2/app/api/routers/gis.py` | 36573 | `325033f3e6a83b24f14f3b7d8d307d9673d74fb2465481b71e24e7b8cdc8060b` |
| `backend-v2/app/api/routers/cables.py` | 3307 | `d0aadff1d1b6336ef3720bb8e569c943728c5e12a188c97bc01841ead0932698` |
| `backend-v2/app/main.py` | 9031 | `fcbf34a9970c6c966c05aef0fa1d9f2622a91ce5d5c8d558db1d0bdc531b8972` |
| `backend-v2/alembic/versions/0016_stage2_equipment.py` | 14928 | `a5de5fb5c776a25a8c612613fa93c92751510488eff835c42ea88aa0d2992a9e` |

Хеши всех 14 файлов `app/`, которые менял t1, **совпадают** с `33a-db-stage2.md` §7 —
значит, qa_agent приложение не трогал. Полный манифест — приложение A.

## 8. Что не делалось (границы t3)

* `backend-v2/app`, `backend-v2/alembic`, `src-v2` — не менялись;
* рабочая `karier_db` — только read-only проверка (head `0015`, 12 объектов, без
  `cable_asset_id` и `razedinitel`); миграции к ней не применялись;
* `tests/test_migrations.py` — 3 теста пропущены (нужна отдельная БД под цикл миграций);
* параллельных прогонов pytest не было; каждый прогон — на `karier_test_db`.

## Приложение A. Полный манифест `app/` и `tests/` (SHA-256)

### backend-v2/app — 80 файлов

| Файл | Размер | SHA-256 |
|---|---:|---|
| `backend-v2/app/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/app/api/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/app/api/deps.py` | 3025 | `152f26d0511270a824ef684ca37f9bd06f75c909ddde6d743733f1e3a41068a0` |
| `backend-v2/app/api/middleware.py` | 2680 | `3417177998a349e5eaeda957b629710e8d8250955171bdf13e4231204d718072` |
| `backend-v2/app/api/routers/__init__.py` | 484 | `415625a90a43e86307b8e93a8d251e94b044057848825d4234fcc3cc08b84013` |
| `backend-v2/app/api/routers/audit.py` | 1950 | `4f9671562ebe3c923be0fd5c6758fb91d8757829221f03c63b37feeb049e20b9` |
| `backend-v2/app/api/routers/auth.py` | 9052 | `510171040f8f15fb129e73b6f764460b090af5d111cbdf3f4199968e3bd24956` |
| `backend-v2/app/api/routers/cables.py` | 3307 | `d0aadff1d1b6336ef3720bb8e569c943728c5e12a188c97bc01841ead0932698` |
| `backend-v2/app/api/routers/defects.py` | 3689 | `140272a2bfbf2b03e0e6fdebaa3f2a23b289578bcefc1e1b6f59fd99d684b1ac` |
| `backend-v2/app/api/routers/documents.py` | 4733 | `ffac08b9f34e58afe72801510e34a06e9d4724c3d513a1a8234895863d9c4a37` |
| `backend-v2/app/api/routers/employees.py` | 14716 | `e98be7680bad8d67e4182122458353be34c93bdd51b0a12f04190d4a8b2a677c` |
| `backend-v2/app/api/routers/gis.py` | 36573 | `325033f3e6a83b24f14f3b7d8d307d9673d74fb2465481b71e24e7b8cdc8060b` |
| `backend-v2/app/api/routers/health.py` | 724 | `6d23a1542d4278eafcc42fc1f7651fdf14e48aa9b4e5043027af27afdb7a1082` |
| `backend-v2/app/api/routers/inspections.py` | 3596 | `d5905a0501aad04c5a80a26d8e9c7fb66f44244739e04593cb12deb98740fc34` |
| `backend-v2/app/api/routers/map_layers.py` | 3934 | `1cc9b928aebcebe71cb6dabd741c16c1b70eb90a9b43b696b9eb693ae61559dc` |
| `backend-v2/app/api/routers/me.py` | 4592 | `3eb3d5ceb43ca729d3d099b87fa897db1c58123dc5ccd18057885df23172a801` |
| `backend-v2/app/api/routers/media.py` | 5066 | `488b37903bf4172d9abd95e2d715eae481f8ab2708100d99b71fad037d29f806` |
| `backend-v2/app/api/routers/moves.py` | 1506 | `f9ca4f5f62c5ae03ef1791a47c61a91a4c557f58875b59db3a1823be2169dc25` |
| `backend-v2/app/api/routers/reports.py` | 4549 | `390b50a6f214de10534ce4d3feb213127acffddf595e0df55d1430b0f29231aa` |
| `backend-v2/app/api/routers/schema_blocks.py` | 16452 | `ea1ab16aa696cd67e9b4cf64ce487c4378e547ee080d40432b4680621a83f7d2` |
| `backend-v2/app/api/routers/sync.py` | 2213 | `927732b472dc1ef4db2bd3011c1d8ca0e9b804d241c78570cea76e7bedc23013` |
| `backend-v2/app/core/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/app/core/config.py` | 6402 | `b8a0c70cddec255acd2d8ec562086bb5a066840e95ad6e3a567fd68ba5181adc` |
| `backend-v2/app/core/errors.py` | 2882 | `bd6191cbdf0d4b8769b99512186103ece89f89706d2c87ff0710f41c79fe9dca` |
| `backend-v2/app/core/ids.py` | 1054 | `e069c17242ebf85ebf4eb9a310045781d13919d5ff165ad39e62b69735a3f26a` |
| `backend-v2/app/core/rate_limit.py` | 2807 | `707cd77c07d824d2971a98a4b2ee1beec8b171ee739dac787c67f6a23a67787b` |
| `backend-v2/app/core/security.py` | 9167 | `cb45e764e0b03e21d1c88d1c5b604374b1461125e67485832cf3a6322c3597c2` |
| `backend-v2/app/db/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/app/db/session.py` | 782 | `d74ad3d8af7d152357da29c5b8cc557237acb6bae26e55ee6ebd1e0bba6bab5b` |
| `backend-v2/app/main.py` | 9031 | `fcbf34a9970c6c966c05aef0fa1d9f2622a91ce5d5c8d558db1d0bdc531b8972` |
| `backend-v2/app/models/__init__.py` | 1251 | `e548625e5180127d1e760dbcb41b794b1bc47e3affbc3c5ccaaf5756f61ad769` |
| `backend-v2/app/models/audit.py` | 1431 | `cc4efe0ee085d9b10a1527d5a6c18ee679b0a514132f734d66337d06c667c46b` |
| `backend-v2/app/models/auth.py` | 10037 | `275c7edcf5cc25ef123bfccd437fc5fe236098d1a551485ff7923181967464eb` |
| `backend-v2/app/models/base.py` | 945 | `a136ac6c8715ed40d28b20374cb966edb301f26688d0cb41744d0e29ce374bd6` |
| `backend-v2/app/models/documents.py` | 1766 | `4730631e91905be357a9d4c77c872b5ab402f2ecaae9429d7ac148f61bd1546c` |
| `backend-v2/app/models/gis.py` | 16966 | `bf685d27e44562b92721abe94581e981b62b03e4b3f2882e7d4ee0bc15c02ede` |
| `backend-v2/app/models/ops.py` | 8221 | `3f09a332d4a594cd1a2c0c8421ccad96d8617bb2fd511aea325251833fcf208a` |
| `backend-v2/app/models/sync.py` | 4419 | `daaf3a363a31188a7deb83a1e2880427afd9367884ba70b4a651b64980c5ea6f` |
| `backend-v2/app/models/topology.py` | 7628 | `25a6a90a95e11a09f4ceb8248bf53bf588873099e4a885534568c43f2e202546` |
| `backend-v2/app/schemas/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/app/schemas/audit.py` | 759 | `31a5f5846ec433a4ed118c6353592ed80902de52c45ca03eb141a063cc76b993` |
| `backend-v2/app/schemas/auth.py` | 3750 | `2604b3064cbe6bfb3f321e2d230f3b43139a99b9523bcfa30b1fd52521a6615f` |
| `backend-v2/app/schemas/common.py` | 282 | `d63ddd9c8506d509f950e2077e6bafd719f97432d753da4c367acd3d3c23055c` |
| `backend-v2/app/schemas/documents.py` | 794 | `f4ac6103d3314ad1abc2e14984e4fb49c9c78e1b42bc0ab51eba2eca58db3762` |
| `backend-v2/app/schemas/employee.py` | 3221 | `e0e6c9ae9f8f30165eb205c484776c3a97258955b8f852b0718364b1c3d82ec6` |
| `backend-v2/app/schemas/equipment.py` | 6070 | `9db2e4089bee1360068acc0dee32b8d82f52d8adcac7c589139aa1374d66f561` |
| `backend-v2/app/schemas/gis.py` | 28405 | `e4781d65243c9bf514baa5992943114ed9f248d7f0f0f0106766a0db27e464dd` |
| `backend-v2/app/schemas/ops.py` | 4343 | `c69ad0e0d012591eefca1cf92c088f56f682995e2744072f89ad381a49fe0714` |
| `backend-v2/app/schemas/sync.py` | 2592 | `5976037adc551d4f9dfc897bedf78af85e89372f771428d1b2d81c7685db9792` |
| `backend-v2/app/seed_equipment_model.py` | 3502 | `02b81e8abfae07cb2e38986cc548e60f5053742c2e93a0db8de9b7557f81a853` |
| `backend-v2/app/services/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/app/services/ai_tools.py` | 6658 | `dbbf3482653bfc4613f26f8591a221b5ce936e60a7feb98fd15e00aaf97a34b3` |
| `backend-v2/app/services/analytics.py` | 4745 | `070f63cc36130edc35fee295fe7544ba53afc5aa662d1cbf3a8b300c61013384` |
| `backend-v2/app/services/asset_fields.py` | 31060 | `c6ebc6efec8961166c71de1ebbda706e81918e976dd8cbe1dbd6513f735b8017` |
| `backend-v2/app/services/audit.py` | 4304 | `4d2bc83ce7ab4eaff9cdc16a13270270f855dc85266c50f7f7348fa15b9c9783` |
| `backend-v2/app/services/auth.py` | 28548 | `88f884810b7c9527f50c817ece1b87de1ed4ec909e3011c0a71013ca5d4374e6` |
| `backend-v2/app/services/break_glass.py` | 5654 | `f82eae632493c58267e0ab35ff42543e3fd5ad275d9de343c176a096d458d099` |
| `backend-v2/app/services/cables.py` | 16790 | `0163d22f80d6c524428438ee06c0aa999808dd7988d4c405a491402e3cc249f7` |
| `backend-v2/app/services/composite.py` | 15270 | `cc1ad97f503a501f965e9673d5137dc34d70c11cfc8dd4c9931040354faaf963` |
| `backend-v2/app/services/defects.py` | 9941 | `5d3caafe70ef1b943e7af29d027e76ac822c0db6c882d6af4b85f1ffb96375c7` |
| `backend-v2/app/services/documents.py` | 8439 | `0b9f1d364c1f36a7c9cce68938bd74c1c6713492e506491b0066e527da8c439b` |
| `backend-v2/app/services/equipment_templates.py` | 24833 | `b4584e7553b56c575280a30214e7dd23a5d6fbc92f2326ad7abc69ca808cd89a` |
| `backend-v2/app/services/gis.py` | 37090 | `aa767b923f32d8d07a2d2c90a2fac9fc0868766dcc541bdfa8cbc97c57aca990` |
| `backend-v2/app/services/groups.py` | 4437 | `ae91f4c8121e5161085b58673c8b696cdde40a6b9d31a9911ff3c4ffd59cd776` |
| `backend-v2/app/services/inspections.py` | 7288 | `de044e78424fedada19e0967b05257f416ec36287de015f24f01b34ade09ba24` |
| `backend-v2/app/services/links.py` | 11635 | `6d39ff50b3621cfbd43ce143692531dec5ad4354767f9f4feb6a5f781e5ebe53` |
| `backend-v2/app/services/maintenance.py` | 2569 | `09beff856c5e9720f291acc488ea904dc83ba62cdbf37de629689b41ae85be50` |
| `backend-v2/app/services/media.py` | 6207 | `cb88017967253ecebd05adb476292ff19a2e27fbb5bf8bc277d97e9ff024a5ce` |
| `backend-v2/app/services/moves.py` | 3247 | `60b7e48f253fa49492a015e66c7d25e369baed0df527657a87c7a01781e13a78` |
| `backend-v2/app/services/notify.py` | 3683 | `7cda65759af075431207e0e8b8b2f2bc2912542656c74ca8cccb3c66a9826ca9` |
| `backend-v2/app/services/poles.py` | 11927 | `ab309a0e5e5cb78ec01d8b1b072599923827e9d57a2322d6005c781d1f41e1ca` |
| `backend-v2/app/services/reports.py` | 17429 | `d79b290432cea592d766f1c0c2e13bb875e299a90f60c728fa64e0be85331628` |
| `backend-v2/app/services/schema_blocks.py` | 42053 | `3b6c5778c6ccab3d3179c635bf7497103d5a7e78d429ae8850585d2c701ade1b` |
| `backend-v2/app/services/schema_graph.py` | 8845 | `335f3863176f0e18e968839ee43aa61e49e0a1eda08ef90f09a291dbeda5523f` |
| `backend-v2/app/services/schema_pdf.py` | 7107 | `06da8fe7d68268c7214607c191da8aae606b894f099203ca802b2c59336b9edc` |
| `backend-v2/app/services/schema_snapshots.py` | 5162 | `a1924082578f3b0f9328cbc00467ef575439570f72b9206c25eccfb120fe3eea` |
| `backend-v2/app/services/state.py` | 9976 | `131256c20c43d51a650fe2a0bfa8ac0de3709e9f1fb702085dd643cc9fb7a1fc` |
| `backend-v2/app/services/storage.py` | 4287 | `96ef419764765f8accd8eb9b81e2846e3fabd8845773449d37f152a5832e5d65` |
| `backend-v2/app/services/sync.py` | 19244 | `02657620d8d0ae56c4a69165d7d69892a6633b9beda7bcbd43c1ef7a12bebe64` |
| `backend-v2/app/services/topology.py` | 23609 | `f4d4d0a1af53f693fa32c51cad58ceef679c0fc48e9d1377cacd56956cb5c350` |

### backend-v2/tests — 34 файлов

| Файл | Размер | SHA-256 |
|---|---:|---|
| `backend-v2/tests/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `backend-v2/tests/conftest.py` | 13029 | `40b99ab45351011599251baa2dee6bcde37fcb47dfd1caad9c6522eb0453ccc9` |
| `backend-v2/tests/test_admin_api.py` | 11354 | `709b7cce29a4b7da1b9e3d4e28e39bbe2ef37b9769188fe0d2e96f1c2f82a924` |
| `backend-v2/tests/test_api_contract_validation.py` | 3539 | `b2e31727bd4266cb524aeab51a24b28779cec8051d3422675bd54b6af93bf595` |
| `backend-v2/tests/test_auth_api.py` | 13441 | `5d69ab385ec71e7d248fb1e33439ad0933b5f83a31f979f0507903fad1ab5d34` |
| `backend-v2/tests/test_blocks_s18.py` | 5725 | `14aa5a17cbb710b0e123b45c72442c56a7a3f3f80e7918906709580fab3b5823` |
| `backend-v2/tests/test_blocks_s20.py` | 1859 | `2006c84c3124fb9480306144fb01bc53dd30f9a175ef82d1f382601154e801fb` |
| `backend-v2/tests/test_blocks_s21.py` | 2929 | `29747af232be87073db1539b4c6546159c517b059d0fd1b5c47b335310ccb31f` |
| `backend-v2/tests/test_break_glass.py` | 4800 | `101b68ad88c4b5abbb2959f455142ccafecfcd5abd4234ce003dec2aa53deca3` |
| `backend-v2/tests/test_documents_security.py` | 3611 | `f1656bdd109dc057e2e001ed804895b3c99a71c4d39076b74c46e986c228ee7e` |
| `backend-v2/tests/test_equipment_fields.py` | 19432 | `0d05e371b90cd97d031e477d9d6092fa8f1d5d3e392eee863e57afbd5dfc2cab` |
| `backend-v2/tests/test_final_api.py` | 3917 | `976868d580cf59fe77f38862710e766a44af2c935a04d6041f2729256400f4f3` |
| `backend-v2/tests/test_gis_api.py` | 7864 | `a0afe699c28e103df2b8c79a9b00cdbcf452770fcc370c383d1c6cc69f01e243` |
| `backend-v2/tests/test_gost_schema.py` | 5205 | `da7a8bbbcfdf018240d942b152aee243c4d44a8a77efecd7062124e3446caaf8` |
| `backend-v2/tests/test_line_builder.py` | 10373 | `0f6728e1c9400e974ec4649ae50cf27e2e18ac5a222c57be1c53e6a14b892816` |
| `backend-v2/tests/test_mcp_tools.py` | 6274 | `abd924ebe6942e21506b3b0792bb15d01f41a4cc05d573bb89f600b3ef420734` |
| `backend-v2/tests/test_migrations.py` | 14071 | `d662572b43472064c11b1e6f4c3a7187dcd3af504c7f458b63306a7ee41525ed` |
| `backend-v2/tests/test_ops_api.py` | 7700 | `720e08bcf18f471208a9ccd84509edb478b799b71fe4735bc87800455714c593` |
| `backend-v2/tests/test_reports_api.py` | 3226 | `8aa91567e32b93c80e1668a7797d541d98bd32719fe115d860f697faa53856d4` |
| `backend-v2/tests/test_schema_blocks.py` | 6448 | `861ab11e37fc2afeae3efdc0a56258adf85a71c9a4517be64d8c95950f5e78e4` |
| `backend-v2/tests/test_schema_builder.py` | 29467 | `b8630c825fb174dccefd661ee8b7887978b21af32b8c73fa7e91c9076c3438cd` |
| `backend-v2/tests/test_schema_snapshots.py` | 7194 | `3fd5802608c37e94373d2c8d47281c30591fb9a988f0bd2266ba5c1f87ed72cb` |
| `backend-v2/tests/test_security_ip.py` | 3766 | `d18d24e8e784c9a7d7c43c9f4da3705ab619dfc07ee8689195c858bf47659f9b` |
| `backend-v2/tests/test_sketch_v2.py` | 5608 | `92314aa9a252e52a9b19437b12cd717a2b352646dcb32cf504a7f32f945c4548` |
| `backend-v2/tests/test_sketch_v3.py` | 5214 | `3910489bc5200b3145456caa3073cc75a40df73b62b269fe33656cc412616b6a` |
| `backend-v2/tests/test_sketch_v4.py` | 5168 | `8302a1702b90b50f93c0705eae65d44c9dfee6dbba2090c5a209e5f7d17fd2c0` |
| `backend-v2/tests/test_sketch_v5.py` | 4286 | `68a10b6a6182bdd559cb8293f700448e20ce3f81fca44f3ca0bba61b90eb70a6` |
| `backend-v2/tests/test_sketch_v6.py` | 3724 | `7832cee480966963ecdc70320adda5ca736d361406fe00cadc7418dc085bc997` |
| `backend-v2/tests/test_sprint12_api.py` | 6800 | `a5d4dcd78ee051fd9de55ec05a09d41f3e528d56cb4527a63689712e6dcaa8b8` |
| `backend-v2/tests/test_stage2_equipment.py` | 44155 | `7f371e5d91ecdc66802401d414565f844ab2fbef5130a12496cc41e20dfa521a` |
| `backend-v2/tests/test_sync_api.py` | 21399 | `023f433a93ef388777e5e0452db2b54463da6a5d11616d39cff82ab19301a984` |
| `backend-v2/tests/test_topology_api.py` | 16087 | `79f3a400c62177d148bd52f3e264a159abe9390f4d8885960a2e271383a7620b` |
| `backend-v2/tests/test_undo_restore.py` | 4306 | `96eb1cb1a1961db743167e6be24e8ae821b6b5bca60c64690650c7ac59e15245` |
| `backend-v2/tests/test_ux_api.py` | 7400 | `f4463fed7bcc70931eee2e9d49bf1a3671909469a96ce7d659f3b8bfa5614a05` |
