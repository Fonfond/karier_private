# 21 — S-1d: коммит инфраструктуры CI (закрытие R1b-4)

**Дата:** 2026-11-25, 21:44–21:50 (локальное время машины, UTC+08:00)
**Кто:** `integrator` (задача t33, команда `karier-improvements`)
**Основание:** находка R1b-4 (`docs/team/18-r1b-review.md` §7): инфраструктура S-3 лежала в рабочем
дереве untracked (`.github/`, `pytest.ini`, `test_migrations.py`, `check_migrations.sh`) и потерялась
бы при `git clean` или уборке дерева.
**Рамки:** сделан **один** коммит только с пятью явно перечисленными путями. Не использовались
`git add -A/-u`; не коммитились `backend-v2/requirements.txt` (WIP владельца), `app/`, `tests/`
(правки S-4/S-9), `.env*`, `docs/**` и фичи волны. `push` не выполнялся, remote не менялся.
Записан один файл — этот отчёт.

---

## 1. Коммит

| Параметр | Значение |
|---|---|
| Хеш (полный) | `1d1d146bab52b6fb1bf8c2d98005c25574f3ff1b` |
| Хеш (короткий) | `1d1d146` |
| Сообщение | `chore(ci): workflow, pytest-конфиг и тест миграций (S-3)` |
| Автор / коммиттер | `Sergey <dandjeydee@gmail.com>` (идентичность владельца, задана в S-1c) |
| Ветка | `feature/sprint-29-maintenance-cables` (без upstream, `push` не было) |
| Изменения | **5 файлов, +666 / −1** |
| Родитель | `a46d16a` (гигиена S-1c) |

```
.github/workflows/ci.yml               | 200 ++++++++++++++++++++++
backend-v2/pytest.ini                  |  20 +++
backend-v2/scripts/check_migrations.sh | 144 ++++++++++++++++
backend-v2/tests/test_migrations.py    | 300 +++++++++++++++++++++++++++++++++
src-v2/package.json                    |   3 +-
5 files changed, 666 insertions(+), 1 deletion(-)
```

---

## 2. Что вошло и почему именно эти пути

| Путь | Статус в коммите | Что это | Источник |
|---|---|---|---|
| `.github/workflows/ci.yml` | новый (`A`) | CI из трёх job'ов: backend (postgres:18, seed-сборка тестовой БД, pytest с покрытием + артефакт), frontend (typecheck/build/vitest), migrations (upgrade→downgrade→upgrade + сверка autogenerate с baseline) | S-3 (t13), правка S-3c (t32) |
| `backend-v2/pytest.ini` | новый (`A`) | конфиг pytest: `--strict-markers`, `--strict-config`, `--durations=20`, маркеры `slow`/`integration`, `testpaths` | S-3 (t13) |
| `backend-v2/tests/test_migrations.py` | новый (`A`) | тесты миграций: одна голова, цикл upgrade→downgrade→upgrade, baseline 29 известных расхождений, защита от рабочей/тестовой БД | S-3 (t13) |
| `backend-v2/scripts/check_migrations.sh` | новый (`A`) | локальный аналог migrations-job на одноразовой БД | S-3 (t13) |
| `src-v2/package.json` | изменён (`M`) | добавлен скрипт `"ci": "npm run typecheck && npm run build && npm run test"` (+2/−1, ничего другого в диффе нет) | S-3 (t13) |

Все пять путей проверены перед коммитом: файлы существуют, `git diff` для `package.json` содержит
только добавление скрипта `ci`, в остальных файлах — только их собственное содержимое (S-3).

---

## 3. Состояние дерева: до и после

### 3.1. До коммита (21:44)

`git status --porcelain` — **52 записи**: 29 modified + 23 untracked. В том числе целевые для S-1d:

```
 M src-v2/package.json
?? .github/
?? backend-v2/pytest.ini
?? backend-v2/scripts/check_migrations.sh
?? backend-v2/tests/test_migrations.py
```

Остальное — WIP владельца (правки волны: `backend-v2/app/**` 16 файлов, `src-v2/src/**` 7 файлов,
`backend-v2/tests/**` 4 файла, `.gitignore`, `backend-v2/requirements.txt`) и новые файлы фич/доков
(`0014_schema_snapshots.py`, `schema_graph.py`, `schema_snapshots.py`, 6 новых тестов,
3 панели карты, `vite.test.config.mjs`, `docs/50…54`, `docs/team/`).

### 3.2. После коммита (21:47)

`git status --porcelain` — **47 записей**: 28 modified + 19 untracked. Исчезли ровно пять записей из
§3.1 (`M src-v2/package.json` и четыре `??`). Проверено, что ничего лишнего не добавилось и ничего
из чужого не закоммичено:

```
 M .gitignore                      ← S-3b (правила покрытия), НЕ входит в этот коммит
 M backend-v2/requirements.txt     ← WIP владельца (openpyxl/reportlab/pillow + pytest-cov), НЕ входит
 M backend-v2/app/**               ← S-4/S-9 и WIP владельца, НЕ входит
 M backend-v2/tests/**             ← S-9, НЕ входит
?? backend-v2/tests/test_api_contract_validation.py … test_undo_restore.py   ← WIP, НЕ входит
?? docs/**                        ← отчёты и гайды, НЕ входят
```

`git diff --cached` после коммита пуст; индекс чист относительно HEAD.

---

## 4. Проверки

| # | Команда / проверка | Результат |
|---|---|---|
| 1 | `git log -1 --stat --oneline` | `1d1d146 chore(ci): workflow, pytest-конфиг и тест миграций (S-3)` + ровно 5 файлов, `+666/−1` |
| 2 | `git ls-files -- .github/workflows/ci.yml backend-v2/pytest.ini backend-v2/tests/test_migrations.py backend-v2/scripts/check_migrations.sh` | **4 пути** в индексе → `infra-tracked` |
| 3 | `git status --porcelain \| Select-String 'requirements.txt\|\.env'` | только ` M backend-v2/requirements.txt`; **ни одного `.env`** (не в индексе и не в коммите) |
| 4 | `git show --name-only --format='' HEAD` | ровно 5 путей; фильтр `requirements.txt\|^backend-v2/app/\|^backend-v2/tests/(?!test_migrations)\|\.env` — **0 совпадений** |
| 5 | `git diff --cached --name-status` до коммита | `A .github/workflows/ci.yml`, `A backend-v2/pytest.ini`, `A backend-v2/scripts/check_migrations.sh`, `A backend-v2/tests/test_migrations.py`, `M src-v2/package.json` — ровно 5, без `-A/-u` |
| 6 | `git remote -v` / upstream | `origin = https://github.com/Fonfond/karier-app.git` (не менялся), upstream у ветки отсутствует → `push` не выполнялся |
| 7 | Хуки | в `.git/hooks` нет активных хуков (только `.sample`) — коммит не проходил через дополнительную автоматику |

Замечание по процессу: команда-обёртка с коммитом и последующими проверками отчиталась о завершении с
задержкой (git-процесс уже завершился, `commit_exit=0`; `index.lock` отсутствует, повторных коммитов
нет). Это артефакт оболочки, а не git: в истории ровно один новый коммит `1d1d146`.

---

## 5. Что осталось незакоммиченным (и почему это нормально)

| Группа | Что | Причина |
|---|---|---|
| Инфраструктура гигиены | `.gitignore` (+правила `.vs/`, `.vercel/`, покрытие — S-1c закоммичен, блок S-3b ещё нет), `backend-v2/requirements.txt` (+`pytest-cov==6.3.0` и пины владельца) | WIP владельца и S-3b; отдельная задача/коммит владельца |
| Код волны | `backend-v2/app/**` — 16 файлов (`main.py`, `services/gis.py`, `services/sync.py`, `core/*`, `models/*`, `routers/*`, `schemas/*`) | незавершённые S-4/S-9 и WIP владельца |
| Тесты | `backend-v2/tests/**` — 4 изменённых + 6 новых (в т.ч. `test_migrations.py` уже в коммите, остальные — нет) | S-9 в процессе |
| Новые файлы фич | `alembic/versions/0014_schema_snapshots.py`, `app/services/schema_graph.py`, `schema_snapshots.py`, 3 панели карты, `vite.test.config.mjs` | ждут ревью/коммита владельца |
| Документы | `docs/50…54`, `docs/team/**` | отчёты команды, коммитятся отдельно по решению владельца |

R1b-4 закрыт: инфраструктура CI больше не потеряется при очистке дерева. Перед публикацией остаётся
закоммитить `requirements.txt` + `.gitignore` (S-3b), файлы фич и документы, а после завершения S-4/S-9 —
сделать V1c (привязка вердикта к новым байтам, `docs/team/18-r1b-review.md` R1b-1).

---

## 6. Приложение: команды

```powershell
$g = 'C:\karier\tools\MinGit\cmd\git.exe'; $r = 'C:\karier\karier'

# 1) снимок состояния ДО
& $g -C $r status --porcelain        # 52 записи: 29 M + 23 ??

# 2) явные пути, без -A/-u
& $g -C $r add -- .github/workflows/ci.yml backend-v2/pytest.ini `
    backend-v2/tests/test_migrations.py backend-v2/scripts/check_migrations.sh src-v2/package.json
& $g -C $r diff --cached --name-status        # ровно 5: 4×A + 1×M

# 3) коммит
& $g -C $r commit -m "chore(ci): workflow, pytest-конфиг и тест миграций (S-3)"
#    1d1d146bab52b6fb1bf8c2d98005c25574f3ff1b

# 4) проверки
& $g -C $r log -1 --stat --oneline
& $g -C $r ls-files -- .github/workflows/ci.yml backend-v2/pytest.ini `
    backend-v2/tests/test_migrations.py backend-v2/scripts/check_migrations.sh   # 4 пути
& $g -C $r status --porcelain | Select-String 'requirements.txt|\.env'            # только requirements.txt
& $g -C $r status --porcelain        # 47 записей: 28 M + 19 ??
& $g -C $r remote -v                 # без изменений; push не выполнялся
```
