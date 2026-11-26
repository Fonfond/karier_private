# 20 — S-3c: убрать дублирующую установку pytest-cov в CI

**Дата:** 2026-11-25, 11:00–11:15 (локальное время машины, UTC+08:00)
**Кто:** `integrator` (задача t32, команда `karier-improvements`)
**Основание:** рекомендация S-3b (`docs/team/17-s3b-coverage.md` §5.1): после пина
`pytest-cov==6.3.0` в `backend-v2/requirements.txt` отдельная установка `pip install "pytest-cov>=5,<7"`
в CI стала избыточной и, что важнее, **шире пина** — CI мог поставить версию, отличную от локальной.
**Рамки:** изменён только `.github/workflows/ci.yml` (+ этот отчёт). `backend-v2/requirements.txt`,
`app/`, `tests/`, `src-v2` не тронуты; pytest не запускался; `karier_db` не затрагивалась.

---

## 1. Итог

| Что | Было | Стало |
|---|---|---|
| Шаг установки зависимостей (job `backend`) | «Зависимости (requirements + pytest-cov)»: `pip install -r requirements.txt` **+** `pip install "pytest-cov>=5,<7"` | «Зависимости (requirements)»: **только** `pip install -r backend-v2/requirements.txt` — `pytest-cov==6.3.0` приходит из файла |
| Версия покрытия в CI | диапазон `>=5,<7` (мог отличаться от локальной) | ровно `6.3.0`, как в `requirements.txt` и в venv |
| Порог покрытия | `--cov-fail-under=0` в командной строке pytest | **убран** (по контракту: до S-9 порога не вводим; по умолчанию порога нет, поведение не меняется) |
| Отчёт покрытия | `--cov-report=term-missing --cov-report=xml:coverage.xml` + артефакт `backend-coverage` | **без изменений** — только отчёт |
| Упоминаний `pytest-cov` в workflow | 2 (имя шага + строка установки) | **0** |
| YAML | — | валиден (`yaml.safe_load` → `yaml-ok`, 3 job'а: backend/frontend/migrations) |

---

## 2. Что именно изменено

Единственный файл — `.github/workflows/ci.yml`. Два места, job `backend`:

### 2.1. Шаг зависимостей (было строки 73–77)

```yaml
# БЫЛО
      - name: Зависимости (requirements + pytest-cov)
        run: |
          python -m pip install --upgrade pip
          pip install -r backend-v2/requirements.txt
          pip install "pytest-cov>=5,<7"

# СТАЛО
      - name: Зависимости (requirements)
        run: |
          python -m pip install --upgrade pip
          pip install -r backend-v2/requirements.txt
```

Причина: `backend-v2/requirements.txt:22` уже содержит `pytest-cov==6.3.0` (S-3b/t29), поэтому
отдельная установка не нужна. Дополнительный эффект: шаг `actions/setup-python` кэширует pip по
`cache-dependency-path: backend-v2/requirements.txt` — теперь изменение версии покрытия видно кэшу,
а раньше диапазон жил вне файла зависимостей.

### 2.2. Команда pytest (было строки 111–112)

```yaml
# БЫЛО
            --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml \
            --cov-fail-under=0

# СТАЛО
            --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml
```

`--cov-fail-under=0` убран, а не заменён другим значением: по контракту порог не вводится до S-9
(изоляция тестов) и базовой цифры полного прогона; при отсутствии флага порог и так не применяется,
поэтому поведение CI не меняется — остаётся только сбор отчёта (`term-missing` + `coverage.xml` →
артефакт `backend-coverage`). Строка продолжения `\` у предпоследнего аргумента убрана, чтобы bash не
искал продолжение команды.

Остальное не тронуто: 7 шагов job'а `backend` в прежнем порядке (Checkout → Python → Зависимости →
Создать `karier_test_db` → Схема + seed → pytest → Артефакт покрытия), `--deselect` четырёх
дампозависимых тестов, сервисный PostgreSQL, job'ы `frontend` и `migrations`.

---

## 3. Проверки

| # | Команда / проверка | Результат |
|---|---|---|
| 1 | `Select-String -Path .github/workflows/ci.yml -Pattern 'pytest-cov'` | **нет совпадений** → `no-extra-pytest-cov-step`, exit 0 |
| 2 | `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8'))"` | **`yaml-ok`**, exit 0; `jobs = ['backend', 'frontend', 'migrations']` |
| 3 | `Select-String -Path .github/workflows/ci.yml -Pattern 'cov-fail-under'` | **matches=0** |
| 4 | Структурный разбор загруженного YAML (extra) | backend steps = `Checkout`, `Python ${{ env.PYTHON_VERSION }}`, `Зависимости (requirements)`, `Создать karier_test_db`, `Схема + seed-данные для тестовой БД`, `pytest (полный набор, покрытие)`, `Артефакт покрытия`; `run` шага зависимостей = `pip install --upgrade pip` + `pip install -r backend-v2/requirements.txt` (без третьей строки); `run` шага pytest заканчивается `--cov-report=xml:coverage.xml` без висячего `\` |
| 5 | Сверка с `requirements.txt` (соседний файл, не менялся) | `pytest-cov==6.3.0` присутствует (строка 22) — версия в CI = версия локально = версия пина |
| 6 | `git status --porcelain -- .github` | `?? .github/` — каталог ещё не в индексе (workflow создан в S-3/t13 и не коммитился; это не регресс, но перед публикацией его нужно закоммитить вместе с `requirements.txt`) |

`pytest` в рамках задачи не запускался: изменение не касается кода и тестов, а прогон трогает
`karier_test_db` (в это время шла приёмка V1b).

---

## 4. Влияние и оговорки

1. **Поведение CI не меняется по существу:** pytest по-прежнему собирает покрытие и отдаёт
   `coverage.xml` артефактом; порога не было фактически (`=0`) и нет теперь (флаг отсутствует).
2. **Устранён класс расхождений:** раньше при обновлении `pytest-cov` в `requirements.txt` CI мог
   продолжать ставить другую версию из диапазона `>=5,<7` — теперь единственный источник истины —
   `requirements.txt`.
3. **Порог покрытия** (`--cov-fail-under=<база>`) вводить после S-9 и первого полного прогона с
   покрытием; цифру брать из артефакта `backend-coverage` (сейчас известна только локальная оценка
   одного модуля — 48 %, это не покрытие проекта).
4. **Коммит не делался:** `.github/workflows/ci.yml` untracked (см. §3 п.6) и лежит рядом с WIP
   владельца; при подготовке публикации его нужно добавить в git вместе с `backend-v2/requirements.txt`
   (там же незакоммиченные пины `openpyxl`/`reportlab`/`pillow` — WIP владельца).

---

## 5. Приложение: проверочные команды

```powershell
$r = 'C:\karier\karier'; $py = "$r\backend-v2\venv\Scripts\python.exe"

# 1) в workflow больше нет отдельной установки pytest-cov
Select-String -Path "$r\.github\workflows\ci.yml" -Pattern 'pytest-cov'    # пусто

# 2) YAML загружается безопасно
& $py -c "import yaml; d = yaml.safe_load(open(r'$r\.github\workflows\ci.yml', encoding='utf-8')); print('yaml-ok', list(d['jobs']))"

# 3) порога покрытия нет
Select-String -Path "$r\.github\workflows\ci.yml" -Pattern 'cov-fail-under' # пусто

# 4) версия покрытия — из requirements
Select-String -Path "$r\backend-v2\requirements.txt" -Pattern '^pytest-cov'  # pytest-cov==6.3.0

# 5) состояние git
& 'C:\karier\tools\MinGit\cmd\git.exe' -C $r status --porcelain -- .github  # ?? .github/
```
