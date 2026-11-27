# Этап 2 — шаблоны ячеек, статусы, цвета, кабели: итог

Дата: 26.11.2026 · команда `karier-equipment-stage2` (db_agent, ui_agent, qa_agent) · вердикт t4: **PASS** (с оговорками)

## 1. Результаты по агентам

| Задача | Агент | Итог |
|---|---|---|
**t1** | db_agent | миграция `0016_stage2_equipment`: `links.cable_asset_id` (FK `gis.assets`, `ON DELETE SET NULL`, индекс), `composite_template` v2 + seed БКРУ/ПС/КТП, тип `razedinitel`; API `POST /api/schema/composite`, `POST /api/assets/{id}/toggle`, `GET/POST /api/cables` |
**t2** | ui_agent | мастер «По шаблону» (БКРУ 6, ПС 2×17 с параметром, КТП 0+разъединитель); toggle в узле схемы, карточке и списках; цвета `#F04438`/`#22C55E` везде; кабельные вкладки installed/reserve/repair |
**t3** | qa_agent | `test_stage2_equipment.py` — 12 тестов; полный прогон **226 passed / 3 skipped** |
**t4** | qa_agent | приёмка: миграция up→down→up, API 20/20, браузерный смоук 21/21 (Edge/CDP), цвета и toggle проверены, 19 скриншотов |

## 2. Функциональность

### Шаблоны
- **БКРУ — ровно 6**: Секция 1 — вводная, отходящая, отходящая; секционная (№4); Секция 2 — отходящая, вводная (`in,out,out,sectional,out,in`; секции `1,1,1,1,2,2`).
- **ПС 35/6 — 17 на секцию** (15 отходящих + вводная + секционная), итого 34; параметр `cells_per_section` 1…50, по умолчанию 17; недопустимые → 422 без «полублоков».
- **КТП — 0 ячеек**, создаётся вводной разъединитель (`razedinitel`, `cell_kind=in`), он переключается.

### Переключение и безопасность
- `POST /api/assets/{id}/toggle`: `{status, energized, voltage_kv, nominal_voltage_kv, grounded}`; заземление → `energized=false`; аудит `asset.toggled` в `audit.audit_log` (актор, from/to, причина) + `gis.switching_ops`; viewer 403, не-переключаемый объект 422.
- Кнопка «Включить/Отключить»: узел схемы, карточка, списки/реестр.
- Цвета: **красный `#F04438` = под напряжением**, **зелёный `#22C55E` = обесточено/заземлено**; на схеме (рамка+бейдж), в карточке, списках, легенде, маркерах карты; дублируются текстом/иконкой (⚡/○/⏚), `role=status`, `aria-label`.

### Кабели
- `GET /api/cables?lifecycle_status=`, `install` (на связь или объект), `return` (reserve/repair); `links.cable_asset_id`; статусы `installed/reserve/repair`; аудит `cable.installed/returned`; конфликты → 409, невалидные статусы → 422.
- UI: вкладки installed/reserve/repair, установка/снятие, статус и привязка в таблице и карточке.

## 3. Проверки

| Проверка | Результат |
|---|---|
Миграция 0016 up→down→up на `karier_test_db` | head 0016, данные до/после идентичны (md5 совпали) |
Полный pytest | **226 passed, 3 skipped, 0 failed** (336 с); skip — `test_migrations` без отдельной БД |
Frontend | typecheck 0, build 516 модулей, **vitest 78/78** |
API (TestClient) | 20/20 PASS: шаблоны, toggle+аудит, кабели |
Браузер (Edge/CDP, production dist + backend на тестовой БД) | 21/21 PASS, console errors 0, API ≥400 = 0 |
Цвета | подтверждены на схеме, в карточке и реестре при вкл/откл; состояние сохраняется после перезагрузки |

## 4. Раскатка на рабочую БД (сделано после приёмки)

- бэкап: `C:\karier\.local\backups\karier_db-before-0016-20261126-213846.dump` (0,86 МБ);
- `alembic upgrade head` → **0016**; `cable_asset_id` есть, тип `razedinitel` активен, `composite_template` у БКРУ/ПС/КТП, 82 поля;
- стек перезапущен (API 8001 + Vite 5174, сайт 200);
- OpenAPI: `/api/schema/composite`, `/api/assets/{id}/toggle`, `/api/cables` доступны;
- UI: кнопка **«▤ По шаблону»** в редакторе схемы присутствует, ошибок консоли нет.

## 5. Оговорки приёмки (не блокеры)

1. **F1**: после toggle **из карточки** схема не перекрашивается сразу (данные верны; после перезагрузки цвет корректный). Рекомендация: прокинуть `onChanged` из `AssetSheet` в `MapPage` (3–5 строк).
2. **F2**: «не-ячейка → 400» фактически **422 `asset.not_switchable`**.
3. **F3**: `cells_per_section` — число ячеек всей секции (n=3 → 1 отходящая + 2 служебных; «3+2» — при n=5).
4. **F4**: `/return` не очищает денормализацию `cable_mark/length_m/cross_section_mm2` на связи — продуктовая задача.
5. **F5**: 3 миграционных теста пропущены (нужна отдельная БД; цикл 0016 закрыт ручной проверкой).
6. **F6**: verify-команда без `DATABASE_URL` накатила бы миграции на `karier_db`; приёмка выполнялась с явным `DATABASE_URL=karier_test_db`.

## 6. Артефакты

`docs/team/33a-db-stage2.md`, `33b-ui-stage2.md` (+21 скриншот), `33c-stage2-tests.md`, `33d-stage2-acceptance.md` (+19 скриншотов); тесты `backend-v2/tests/test_stage2_equipment.py`; UI: `CompositeTemplateDialog.tsx`, `PowerStateBadge.tsx`, `PowerToggleButton.tsx`, `lib/power.ts`, `lib/equipmentTemplates.ts`, `CablesPage.tsx`.
