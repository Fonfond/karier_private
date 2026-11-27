# Этап 1 модели оборудования «Карьер»: независимая приёмка

Дата: 26.11.2026 · Исполнитель: qa_agent (t4) · Стенд приёмки: `karier_test_db`,
изолированный API `127.0.0.1:8002`, изолированный Vite `127.0.0.1:5175`
Рабочая БД `karier_db` **не менялась** (только чтение).

## 1. Вердикт

**pass** — с оговорками (§8). Этап 1 закрыт: миграция 0015 применяется и откатывается,
классы и поля типов в БД и API, динамическая форма реестра строит паспорт из полей типа,
серверный 422 объясняет ошибку по-русски (`fields` + `field_labels`), полный регресс и
фронтенд-проверки зелёные, браузерный смоук подтверждает форму и русскую ошибку под полем.

Ограничение независимости: тесты `tests/test_equipment_fields.py` писал тот же qa_agent (t3);
здесь они перепроверены полным прогоном и браузерным смоуком. Второго QA в команде нет.

| Критерий приёмки | Статус | Чем подтверждено |
|---|---|---|
| Хеши `app/`, `tests/`, `src-v2` зафиксированы до и после; миграция up→down→up на `karier_test_db` проходит | ✅ | §2–§3: манифест 213 файлов, SHA-256 манифеста до/после совпал (`9b6dad7e…e85c7`); upgrade → downgrade → upgrade, head `0015_asset_type_fields`, exit 0 |
| Полный `pytest -q`: 0 failed, passed зафиксировано; tsc/build/vitest зелёные | ✅ | §4–§5: **214 passed, 3 skipped, 0 failed** (326.47 с, exit 0); typecheck/build/vitest exit 0, **48 passed** |
| API: `GET /api/asset-types?with_fields=1`; `POST /api/assets` по КТП без полей → 422 `fields`+`field_labels`, с полями → 201, объект удалён | ✅ | §6: 200, 19 типов с `equipment_class/group_code/fields`; КТП с обязательной мощностью → **422** `{"power_kva":"Обязательное поле"}` + `field_labels {"power_kva":"Полная мощность"}`; КТП с полями → **201**, удалён (404). КТП в демо-сиде без обязательных полей — оговорка §8.1 |
| Браузерный смоук: группа класса выбирается, у КТП появляются поля, создание без обязательных даёт русскую ошибку под полем; ошибок консоли/API нет | ✅ | §7: 7 вкладок классов, КТП → 3 поля паспорта; ошибка «Заполните обязательные поля: Полная мощность» + «Обязательное поле» под полем (`aria-invalid`, `aria-describedby`); КТП создан из формы (201); 0 ошибок консоли/`pageerror`/4xx-5xx; скриншоты 70–73 |
| Отчёт с вердиктом и оговорками | ✅ | этот файл, §8 |

## 2. Привязка к байтам (до/после)

Метод: для каждого файла — SHA-256; манифест из строк `sha256  размер  путь (POSIX)` в
детерминированном порядке; затем SHA-256 всего манифеста. Исключены сборочные артефакты:
`node_modules`, `dist`, `.vite`, `__pycache__`, `.pytest_cache`, `*.tsbuildinfo`, `*.pyc`, `*.log`.
Скрипт: `.local/qa-hash-manifest.py` (вне продуктовых каталогов).

| Дерево | Файлов | SHA-256 манифеста до | SHA-256 манифеста после |
|---|---|---|---|
| `backend-v2/app` | 76 | `9b6dad7e206b4646c935d722ad93737c0bce89af1df2241cdb3d26a3019e85c7` (общий) | **совпал** (общий) |
| `backend-v2/tests` | 34 | — | **совпал** |
| `src-v2` (src + конфиги) | 103 | — | **совпал** |
| **Всего** | **213** | `9b6dad7e…e85c7` | `9b6dad7e…e85c7` |

Полные манифесты: `.local/accept-prev1.txt` (до), `.local/accept-post2.txt` (после);
`Compare-Object` — **0 различий**. Продуктовые файлы не менялись: ни один хеш не сдвинулся
(в т.ч. `app/services/asset_fields.py` = `c6ebc6ef…8017`, `tests/test_equipment_fields.py` =
`0d05e371…2cab`, `src-v2/src/lib/assetFields.ts` = `b76dc199…a1ea`,
`src-v2/src/components/asset/DynamicFields.tsx` = `99172a72…94db`,
`src-v2/src/pages/RegistryPage.tsx` = `77d11dff…b739`, `src-v2/vite.config.ts` = `4ffa74ff…7d75`).
`tests` = 34 файла (33 `*.py` + `.env.test`), `src-v2` = 103 (без `node_modules`/`dist`).

## 3. Миграции на `karier_test_db` (up → down → up)

```
powershell -NoProfile -Command "cd C:\karier\karier\backend-v2; $env:DATABASE_URL='postgresql+psycopg://karier_user:***@127.0.0.1:5432/karier_test_db'; .\venv\Scripts\python.exe -m alembic upgrade head; .\venv\Scripts\python.exe -m alembic downgrade -1; .\venv\Scripts\python.exe -m alembic upgrade head; .\venv\Scripts\python.exe -m pytest -q"
```

Важно: `alembic.ini`/`backend-v2/.env` по умолчанию указывают на рабочую `karier_db`, поэтому
DSN тестовой БД задан явно через `$env:DATABASE_URL` (иначе команда из контракта раскатала бы
миграцию на рабочей БД — запрещено). `pytest` в той же оболочке видит тот же DSN, а
`tests/conftest.py` дополнительно падает, если база не `karier_test_db`.

| Шаг | Результат |
|---|---|
| `alembic upgrade head` | 0014 → **0015_asset_type_fields**, exit 0 |
| `alembic downgrade -1` | 0015 → **0014_schema_snapshots** (таблица полей и колонки удалены), exit 0 |
| `alembic upgrade head` | 0014 → **0015_asset_type_fields**, exit 0 |
| `alembic current` | **0015_asset_type_fields (head)** |
| Данные после цикла | 19 типов, 24 поля, 585 живых объектов, классы mobile 9 / distribution 3 / transformer_assembly 3 / cable 1 / switching 1 / cell 1 / line 1 — как до цикла |

## 4. Полный pytest

Тот же прогон (после цикла миграций), один pytest за раз:

```
powershell -NoProfile -Command "cd C:\karier\karier\backend-v2; .\venv\Scripts\python.exe -m pytest -q"
```

**214 passed, 3 skipped, 0 failed**, 601 warning, **326.47 с (0:05:26)**, exit 0.

3 skipped — только `tests/test_migrations.py` (`test_single_alembic_head`,
`test_upgrade_downgrade_upgrade`, `test_autogenerate_has_only_known_drift`): не задан
`TEST_MIGRATION_DATABASE_URL`, цикл `downgrade base` разрешён только на отдельной БД.
Это не регресс: по `32a-db-migration.md` §5 те же тесты проходят на `karier_migrations_test`
(3 passed). Новый файл этапа 1 входит в прогон (10 тестов t3 зелёные).

## 5. Фронтенд (`src-v2`)

```
powershell -NoProfile -Command "cd C:\karier\karier\src-v2; npm.cmd run typecheck; npm.cmd run build; npx.cmd vitest run"
```

| Проверка | Результат |
|---|---|
| `tsc -b --noEmit` (typecheck) | exit 0, ошибок 0 |
| `vite build` | exit 0, 511 модулей, 5.29 с; единственное предупреждение — размер чанка > 500 кБ (существовал раньше) |
| `vitest run` | exit 0, **5 файлов / 48 тестов passed** (в т.ч. `lib/assetFields.test.ts` 23, `components/asset/DynamicFields.test.tsx` 5) |

Сборка создала `dist/` — из хеш-манифеста исключён (как и в 32c), исходники не изменились.

## 6. API-проверки (изолированный API 8002 → `karier_test_db`)

Стенд: `uvicorn app.main:app --port 8002` с `DATABASE_URL=…/karier_test_db` (текущий код,
не stale-процесс 8001). Логи: `.local/logs/accept-api-checks.log`,
`.local/logs/accept-ktp-required.log`.

| Проверка | Результат |
|---|---|
| `GET /api/asset-types?with_fields=1` | **200**, 19 типов; у всех `equipment_class` и `group_code`; у КТП 3 поля: `power_kva` («Полная мощность», number, кВ·А), `voltage_in_kv` («Напряжение на входе», кВ), `voltage_out_kv` («Напряжение на выходе», кВ); у кабеля обязательные `cable_mark`, `length_m` |
| `POST /api/assets` КТП **без полей**, когда мощность обязательна | **422** `application/problem+json`: `detail` = «Проверьте поля объекта: Полная мощность», `fields = {"power_kva":"Обязательное поле"}`, `field_labels = {"power_kva":"Полная мощность"}` |
| `POST /api/assets` КТП **с полями** | **201**, `KTP-165`, `attrs` записаны; удалён → **404** |
| `POST /api/assets` ДМО без паспорта (обязательный `power_kw` в демо-сиде) | **422**, `fields={"power_kw":"Обязательное поле"}`, `field_labels={"power_kw":"Мощность"}`, detail по-русски |
| `POST /api/assets` кабель без паспорта | **422**, `fields={cable_mark,length_m}`, `field_labels={"cable_mark":"Марка кабеля","length_m":"Длина"}` |
| `POST /api/assets` кабель с паспортом | **201**, `lifecycle_status = installed` (0015) |
| Удаление созданных объектов | все созданные объекты удалены (soft delete → 404), строки затем вычищены из тестовой БД; живых объектов снова **585**, `(QA)`-имён 0 |

Нюанс данных: в демо-сиде `karier_test_db` у типа `ktp` `required_attrs = []` (в рабочей
`karier_db` — `{power_kw}`). Поэтому «как есть» КТП без паспорта создаётся (201). Чтобы
воспроизвести исходный сценарий приёмки (КТП как в рабочей БД), обязательность `power_kva`
включена **штатным** `PATCH /api/asset-types/{id}` (`required_attrs=["power_kva"]`) — это
заодно проверка двойной записи 0015 (`attr_schema` ↔ `gis.asset_type_fields`: поле стало
`required=true`). После проверки конфигурация возвращена: `required_attrs=[]`,
все три поля КТП снова `required=false` (сверено запросом и БД). Код не менялся.

## 7. Браузерный смоук (headless Edge, puppeteer-core)

Стенд: Vite **5175** → API **8002** → `karier_test_db`; рабочая `karier_db` и dev-стенд
8001/5174 не затрагивались. Инструмент: `puppeteer-core` + Edge, `headless: 'new'`, сбор
`console`, `pageerror`, упавших запросов и ответов 4xx/5xx. Скрипты:
`.local/browser/check-stage1-form.mjs`, `.local/browser/check-stage1-ktp-required.mjs`
(временная конфигурация Vite — `.local/browser/vite.accept.config.mjs`, вне `src-v2`).
Логи: `.local/logs/accept-browser.log`, `.local/logs/accept-browser-ktp-required.log`.

| Шаг | Результат |
|---|---|
| Вход `000001/admin`, раздел «Реестр» | 200, страница загрузилась |
| Вкладки классов в «Новый объект» | **7 вкладок**: Распредустройства 3, Трансформаторы и сборки 3, Коммутационные 1, Ячейки 1, Кабели 1, Мобильное 9, Опоры 1; первая активна (`aria-pressed=true`) |
| Выбор класса «Трансформаторы и сборки» | селект «Модель (тип)» отфильтрован: КСР, ЯКУ-1Т, КТП (только класс `transformer_assembly`) |
| Выбор КТП | подзаголовок «Тип: КТП … · полей паспорта: 3»; появились поля «Полная мощность, кВ·А», «Напряжение на входе, кВ», «Напряжение на выходе, кВ» (единицы рядом) |
| Создание КТП из формы | **POST 201**, объект `KTP-167`, модалка закрылась, уведомление «Объект KTP-167 создан без координат…»; объект удалён после проверки |
| КТП с обязательной мощностью (см. §6): отправка без поля | красная сводка «Заполните обязательные поля: Полная мощность», под полем — «Обязательное поле», `aria-invalid=true`, `aria-describedby=asset-attr-power_kva-error`; **POST не отправлен** (клиентская блокировка), модалка открыта, ввод сохранён |
| Тип «Кабель» (2 обязательных поля) | «Марка кабеля*» и «Длина*, м» с `aria-required=true`; отправка без них — сводка «Заполните обязательные поля: Марка кабеля, Длина» + две ошибки «Обязательное поле» под полями; POST не отправлен |
| Ошибки | **console errors: 0**, **pageerror: 0**, **requestfailed: 0**, **ответов 4xx/5xx: 0** (единственный POST — 201) |

Скриншоты (`.local/browser/shots/`, SHA-256):

| Файл | Размер | SHA-256 | Что видно |
|---|---|---|---|
| `70-stage1-ktp-fields.png` | 135093 | `650c983ff86d5f4b5c45726cc4f24dc7a8f1cf9ac133c8a7efdd8ee794314be0` | вкладки классов, КТП, 3 поля паспорта с единицами |
| `71-stage1-ktp-created.png` | 106044 | `1890cc3df3b331b5331c075e034461678ee26f0e2c4be5f7aba4ecfe41ac2f92` | КТП создан из формы (уведомление), реестр обновился |
| `72-stage1-cable-required-error.png` | 131187 | `4d6042942ff09fa45f98245caad729eb9010fe55a1853348249c08fce153d086` | русская ошибка под полями «Марка кабеля»/«Длина» |
| `73-stage1-ktp-required-error.png` | 133527 | `24e426c1d774404900abead91077a225dc41379c93a733510dedd11f47851d3d` | КТП: ошибка «Обязательное поле» под «Полная мощность*» |

## 8. Оговорки (не блокируют приёмку кода)

1. **Демо-сид тестовой БД: у КТП нет обязательных полей.** `karier_test_db.ktp.required_attrs = []`,
   тогда как в рабочей `karier_db` — `{power_kw}`. Поэтому «как есть» КТП на тестовой БД
   создаётся без паспорта (201), а его форма показывает 3 необязательных поля. Исходный
   сценарий «КТП → 422» воспроизведён с обязательным `power_kva`, включённым штатным
   `PATCH /api/asset-types` (как в рабочей конфигурации), и конфигурация возвращена.
   Для постоянной демонстрации нужно решение владельца: (а) раскатать 0015 на `karier_db`
   (там у КТП уже есть `power_kw`), либо (б) добавить обязательные поля КТП в демо-сид
   тестовой БД. Это данные/сценарий, не дефект кода этапа 1.
2. **Dev-стенд 8001 запущен до правок этапа 1** (процесс с 14:23, без `--reload`, БД из
   `backend-v2/.env` = `karier_db`), поэтому его `GET /api/asset-types?with_fields=1` ещё
   отдаёт типы без `fields`, а рабочая БД — на 0014. Для ручной проверки нового UI нужно
   перезапустить API (и раскатать 0015 на рабочую БД). Приёмка шла на изолированном стенде
   8002, dev-стенд не останавливался.
3. **3 skipped** — `test_migrations.py` без `TEST_MIGRATION_DATABASE_URL` (нужна отдельная
   БД, см. §4). Для полной приёмки миграций — прогнать `scripts/check_migrations.sh`/аналог
   с `karier_migrations_test` (по 32a: 3 passed).
4. **Этап 2 не входит в приёмку**: ячейки-шаблоны (БКРУ-6, ПС-17/секция), кнопки
   включения/отключения, цвета статусов, `/api/cables`, админ-конструктор полей (маршруты
   `POST/PATCH/DELETE /api/asset-types/{id}/fields`, UI «Модели оборудования»).
5. **Не проверялись**: мобильная вёрстка формы на телефоне, Docker-развёртывание, работа на
   рабочей БД (0014): для неё нужна раскатка 0015 — отдельный шаг деплоя.
6. **Остаточные артефакты тестовой БД**: строки аудита от проверок (`PATCH` типа КТП,
   создание/удаление объектов) и сессии входа admin — штатные следы API, как и после
   pytest-прогонов; продуктовые данные возвращены к канону (19 типов / 24 поля / 585 живых
   объектов / 4700 всего / 0 `(QA)`; КТП снова без обязательных полей).
7. **Предупреждение сборки** о размере чанка (>500 кБ) существовало до этапа 1 и не является
   регрессом (build exit 0).

## 9. Что подтверждает приёмка

- Миграция 0015 **additive** и обратима: up→down→up на тестовой БД, head 0015, данные целы.
- Классы оборудования и поля паспорта живут в БД и API; форма реестра строится из
  `gis.asset_type_fields` (вкладки классов, подписи, единицы, обязательные `*`/`aria-required`).
- Ошибка валидации объясняется по-русски: `detail` + машинные `fields` + русские
  `field_labels`, ошибка рисуется под конкретным полем (браузер подтверждён).
- Старые вызовы `attrs` и типы без полей работают (проверено в t3 и полном прогоне).
- Регресс: 214 passed / 0 failed; фронтенд: typecheck/build/vitest зелёные (48 passed).
- Продуктовые каталоги не менялись за время приёмки (213 файлов, хеши до/после совпали).
