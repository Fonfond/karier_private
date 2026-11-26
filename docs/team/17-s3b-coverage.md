# 17 — S-3b: pytest-cov в requirements и игнор артефактов покрытия

**Дата:** 2026-11-25, 09:55–10:25 (локальное время машины, UTC+08:00)
**Кто:** `integrator` (задача t29, команда `karier-improvements`)
**Основание:** оговорки S-3 (`docs/team/14-s3-ci.md`): в `backend-v2/requirements.txt` не было `pytest-cov`
(CI ставил его отдельной строкой `pip install "pytest-cov>=5,<7"`, то есть версия не была закреплена),
а артефакты покрытия (`.coverage`, `coverage.xml`, `htmlcov/`) не были в `.gitignore`.
**Рамки:** изменены только `backend-v2/requirements.txt`, корневой `.gitignore` и этот отчёт.
Код, тесты, `.env` и `src-v2` не тронуты; `karier_db` не затрагивалась.

---

## 1. Итог

| Что | Было | Стало |
|---|---|---|
| `pytest-cov` в `backend-v2/requirements.txt` | отсутствовал | **`pytest-cov==6.3.0`** (строка 22, в блоке «тесты», после `pytest==8.3.4`); версия ровно та, что установлена в venv |
| `pip install -r requirements.txt` в чистом окружении | `pytest --cov` падал без ручной доустановки | покрытие доступно из коробки (CI-строка с ручным `pip install pytest-cov` стала избыточной — см. §5.1) |
| `.gitignore` | только `coverage/` (строка 61) | +5 правил: `.coverage`, `coverage.xml`, `htmlcov/`, `backend-v2/.coverage`, `backend-v2/coverage.xml` |
| `pytest --cov=app --cov-report=term-missing --cov-report=xml` | не проверялось | **работает**: 3 passed, `TOTAL 48 %`, `coverage.xml` 238 483 Б, exit 0 |
| Артефакты в `git status` | попали бы как untracked | **0 записей** (проверено `git check-ignore` по всем пяти путям) |

Коммит не делался: правки лежат в рабочем дереве вместе с WIP владельца (как и остальные задачи
волны). Артефакты `.coverage` и `coverage.xml` оставлены в `backend-v2/` как результат проверки — они
игнорируются git.

---

## 2. Что сделано

### 2.1. `backend-v2/requirements.txt`

```
 # тесты
 pytest==8.3.4
+pytest-cov==6.3.0
 httpx==0.28.1
```

Версия взята из фактически установленной в venv (`pip show pytest-cov` → `Version: 6.3.0`) и
закреплена точным `==`, как остальные пины файла. Транзитивная зависимость `coverage` при этом
разрешается автоматически (в venv стоит `coverage 7.17.5`; в requirements она не пинится — это
отдельный пакет со своей матрицей, а `pytest-cov==6.3.0` требует `coverage>=7.10.6`, что выполняется).

> Замечание для ревьюера: `backend-v2/requirements.txt` в рабочем дереве **уже** был изменён
> владельцем до этой задачи — незакоммиченные пины `openpyxl==3.1.5`, `reportlab==5.1.0`,
> `pillow==13.0.0` (см. `docs/team/05-edit-review.md` §2.4). `git diff` по файлу показывает и их, и
> мою строку. Моё изменение в этом файле ровно одно: `+pytest-cov==6.3.0` после `pytest==8.3.4`;
> остальные строки не правились, файл сохранён в UTF-8 (CRLF-предупреждение git — косметика от
> `.gitattributes`).

### 2.2. Корневой `.gitignore`

Добавлен блок в конец файла (UTF-8 без BOM, существующие строки не менялись):

```
# Покрытие (S-3b): артефакты pytest-cov / coverage.py
.coverage
coverage.xml
htmlcov/
backend-v2/.coverage
backend-v2/coverage.xml
```

`.coverage` и `coverage.xml` без слэша матчатся на любом уровне, поэтому `backend-v2/.coverage` и
`backend-v2/coverage.xml` — дублирующие, но добавлены явно (требование приёмки и наглядность для
будущих подкаталогов). Прежнее правило `coverage/` (строка 61) оставлено как есть — оно про каталог
отчётов `coverage/`, а не про файлы.

---

## 3. Проверки

### 3.1. Команды приёмки (verify из контракта t29)

| # | Команда | Результат |
|---|---|---|
| 1 | `Select-String requirements.txt '^pytest-cov'` + `python -c "import pytest_cov"` | `pytest-cov==6.3.0`; `pytest-cov-ok 6.3.0` (python 3.14.10), exit 0 |
| 2 | `.gitignore` по шаблону `^\.coverage$\|^coverage\.xml$\|^htmlcov/` | **3 совпадения**, exit 0 |
| 3 | `git check-ignore -v backend-v2/.coverage backend-v2/coverage.xml` | `.gitignore:76:backend-v2/.coverage`, `.gitignore:77:backend-v2/coverage.xml`, exit 0 |
| 4 | `pytest -q tests/test_api_contract_validation.py --cov=app --cov-report=term-missing --cov-report=xml` | **3 passed**, `TOTAL 6146 стмт / 3187 непокрыто / 48 %`, `Coverage XML written to file coverage.xml`, exit 0, 4,46 с |

Команда №4 выполнена в 10:05, **до** указания капитана о стопе V1b; повторно не запускалась
(по ограничению «больше pytest не запускать, karier_test_db не трогать»).

### 3.2. Дополнительные проверки

| Проверка | Результат |
|---|---|
| `pip show pytest-cov` | `Name: pytest-cov`, `Version: 6.3.0`, `Requires: coverage, pluggy, pytest` |
| Пин vs установленная версия | `requirements=6.3.0`, `installed=6.3.0`, **equal=True** |
| `python -m pip check` | `No broken requirements found.`, exit 0 |
| `import coverage` | `coverage 7.17.5` (транзитивная зависимость на месте) |
| Созданные артефакты | `backend-v2/.coverage` 69 632 Б, `backend-v2/coverage.xml` 238 483 Б |
| `git check-ignore -v --no-index` по пяти путям | `.gitignore:73:.coverage`, `:74:coverage.xml`, `:75:htmlcov/`, `:76:backend-v2/.coverage`, `:77:backend-v2/coverage.xml` — все матчатся |
| `htmlcov/` (реальная генерация) | `pytest … --cov-report=html --cov-report=` → 83 файла в `backend-v2/htmlcov/`, exit 0; `git check-ignore -v backend-v2/htmlcov/` → `.gitignore:75:htmlcov/`; в `git status` — 0 записей. После проверки каталог удалён (доказательство зафиксировано здесь), чтобы не держать 83 файла в рабочем дереве |
| `git status --porcelain` | упоминаний `coverage`/`htmlcov` — **0** (при 49 записях WIP владельца и других задач) |
| `git status --porcelain -- .gitignore backend-v2/requirements.txt` | ` M .gitignore`, ` M backend-v2/requirements.txt` — только заявленные файлы |

---

## 4. Что осталось / ограничения

1. **Полный прогон с покрытием не запускался.** `pytest --cov=app` на весь набор — это ~7–8 минут и
   запись в `karier_test_db`; по указанию капитана (V1b, привязка вердикта к текущим байтам) прогон
   остановлен после проверочного запуска на одном модуле. Цифра «48 %» — это покрытие `app/`
   только тремя тестами `test_api_contract_validation.py`, **не** покрытие проекта; базовую цифру
   даст полный прогон в CI (`--cov-report=xml` + артефакт `backend-coverage`).
2. **Чистый venv не создавался** (нет офлайн-колеса/времени): вместо этого проверено, что пин равен
   установленной версии, импорт работает, `pip check` чист, а CI ставит зависимости из
   `requirements.txt`. Это закрывает исходный разрыв (раньше `pytest-cov` не был объявлен вовсе).
3. **`coverage` в requirements не пинится** — версия приходит транзитивно от `pytest-cov==6.3.0`;
   если нужна жёсткая воспроизводимость байт-в-байт, стоит добавить `coverage==7.17.5` отдельным
   пунктом (решение владельца, не требуется для запуска).
4. Артефакты `.coverage` и `coverage.xml` в `backend-v2/` остались после проверки (игнорируются).

---

## 5. Рекомендации (вне scope t29)

1. **`.github/workflows/ci.yml:77`** — строка `pip install "pytest-cov>=5,<7"` теперь избыточна:
   версия приходит из `requirements.txt` (и диапазон `>=5,<7` шире пина, то есть CI мог поставить
   другую версию, чем локально). Предлагается удалить строку и переименовать шаг в
   «Зависимости (requirements)» — это делает S-3c/S-3b-продолжение или сам владелец.
2. После S-9 (изоляция тестов) и получения стабильной базовой цифры — включить
   `--cov-fail-under=<база>` в CI (сейчас осознанно `--cov-fail-under=0`).
3. `backend-v2/scripts/check_migrations.sh` и CI-migrations-job покрытием не пользуются — им
   `pytest-cov` не нужен, пин в requirements на них не влияет.

---

## 6. Приложение: команды

```powershell
$git = 'C:\karier\tools\MinGit\cmd\git.exe'; $r = 'C:\karier\karier'
$py  = "$r\backend-v2\venv\Scripts\python.exe"

# 1) версия, которую фиксируем
& $py -m pip show pytest-cov            # Version: 6.3.0
& $py -c "import pytest_cov; print(pytest_cov.__version__)"   # 6.3.0

# 2) правки
#    backend-v2/requirements.txt: pytest==8.3.4 → +pytest-cov==6.3.0
#    .gitignore: + блок «Покрытие (S-3b)» с пятью правилами

# 3) проверка запуска покрытия (выполнено до стопа V1b; повторно не запускалось)
cd C:\karier\karier\backend-v2
& $py -m pytest -q tests/test_api_contract_validation.py --cov=app --cov-report=term-missing --cov-report=xml
#   3 passed, TOTAL 48 %, Coverage XML written to file coverage.xml, exit 0

# 4) игнор
& $git -C $r check-ignore -v backend-v2/.coverage backend-v2/coverage.xml
& $git -C $r check-ignore -v --no-index .coverage coverage.xml htmlcov/ backend-v2/.coverage backend-v2/coverage.xml
& $git -C $r status --porcelain | Select-String 'coverage|htmlcov'   # пусто
```
