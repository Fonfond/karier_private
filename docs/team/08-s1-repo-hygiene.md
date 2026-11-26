# S-1: гигиена репозитория и очистка секретов из кода

**Дата:** 2026-11-24
**Исполнитель:** backend-auditor (задача t7, команда karier-improvements)
**Статус:** выполнено по варианту A, согласованному с капитаном: критерий «0 совпадений» относится к **отслеживаемым** файлам (`git grep`), `.env*` — служебные, их не трогаем (обновит S-1b/t9 при ротации).
**Границы:** пароль **не ротировался**, `backend-v2/.env` и `backend/.env` **не изменялись**, `push` в remote **не выполнялся**, полный `pytest` не запускался (только `tests/test_auth_api.py`).

---

## 1. Итог

| Что | Результат |
|---|---|
| Git | установлен portable **MinGit 2.47.1** в `C:\karier\tools\MinGit` (winget-вариант требовал бы UAC; портативный — без прав администратора) |
| Репозиторий | уже существовал (`.git` на месте, ветка `feature/sprint-29-maintenance-cables`, remote `origin = https://github.com/Fonfond/karier-app.git` — **публичный**); `init` не потребовался |
| Коммиты | `b88b965` — очистка секретов и гигиена; `bf9fabe` — отдельный коммит renormalize. Push не делался |
| Старый пароль в отслеживаемых файлах | `git grep -l -P '<redacted_db_password>'` → **0**; `git grep … HEAD` → **0** |
| Пароль по рабочему дереву (без `.env*`) | **0** совпадений |
| Тесты | `pytest tests/test_auth_api.py -q` → **9 passed** на `karier_test_db` |
| `venv.broken-20261123-0911` | удалён с диска (8 120 файлов, ~207 МБ), в `git status` отсутствует |

---

## 2. Что сделано

### 2.1. Git

```powershell
# portable-установка без прав администратора (winget-вариант не использовался)
Invoke-WebRequest https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip -OutFile C:\karier\tools\MinGit.zip
Expand-Archive C:\karier\tools\MinGit.zip -DestinationPath C:\karier\tools\MinGit
$env:PATH = "C:\karier\tools\MinGit\cmd;$env:PATH"
git --version   # git version 2.47.1.windows.1

# локальная идентичность только для этого репозитория
git config user.name  "backend-auditor (karier-improvements)"
git config user.email "team@karier.local"
```

Репозиторий инициализировать не пришлось: `.git` уже был, история (35+ веток, `origin/main`) на месте.
**Важно:** commit-автор — служебная идентичность; владелец может переписать её (`git commit --amend --reset-author`) до push.

### 2.2. `backend-v2/tests/conftest.py` — DSN тестовой БД без секрета в коде

Было (`tests/conftest.py:22-27`): `DEFAULT_TEST_URL` с реальным паролем `karier_user` в коде.
Стало (`tests/conftest.py:21-62`):

- `TEST_DATABASE_URL` из окружения, иначе — из `backend-v2/tests/.env.test` (`_read_env_test`, читает `TEST_DATABASE_URL=`/`DATABASE_URL=`);
- если нет ни того, ни другого — **fail-fast** с подсказкой: два варианта настройки и указание, что пароль лежит в `backend-v2/.env`, а `.env.test` — в `.gitignore`;
- сохранены прежние защиты: запрет `DATABASE_URL` не на `karier_test_db`, проверка, что приложение реально подключилось к тестовой БД.

Проверено:
- без `TEST_DATABASE_URL` и без `.env.test` → `RuntimeError` с подсказкой (exit 1);
- с `tests/.env.test` → тесты зелёные.

### 2.3. `backend-v2/app/core/config.py` — заглушки вместо секретов + явная ошибка в prod

- `DATABASE_URL` по умолчанию: `postgresql+psycopg://karier_user:__SET_DB_PASSWORD__@127.0.0.1:5432/karier_db` (`config.py:31-35`);
- `SECRET_KEY` по умолчанию: `__SET_SECRET_KEY__` (`config.py:40-43`);
- добавлен `@model_validator(mode="after") _require_real_secrets_in_prod` (`config.py:97-116`): при `ENV=prod` и заглушке в `DATABASE_URL` или `SECRET_KEY` короче 32 символов приложение падает с внятным `ValueError` («добавьте … в backend-v2/.env»).

Проверено:
- `ENV=dev` + `backend-v2/.env` → `settings.DATABASE_URL` и `SECRET_KEY` берутся из `.env` (длина ключа 37);
- `ENV=prod` в каталоге без `.env` → `ValidationError` с текстом про `DATABASE_URL` и `SECRET_KEY` (exit 1).

### 2.4. `backend-v2/scripts/smoke.ps1` — без пароля и без dev-секретов

- `$env:PGPASSWORD = Get-DbPassword` в двух местах (было `'<redacted_db_password>'`): пароль берётся из `$env:PGPASSWORD` или из `DATABASE_URL` в `backend-v2/.env`, иначе — понятная ошибка со ссылкой на `.env` (`smoke.ps1:22-30`);
- убран захардкоженный TOTP-секрет оператора из `param` (было `'VIKFS…'`): теперь `-TotpSecret` или `$env:KARIER_TOTP_SECRET`, иначе — явная ошибка (`smoke.ps1:15-20`);
- заодно исправлен битый путь по умолчанию: `$Python` теперь `Join-Path $PSScriptRoot '..\venv\Scripts\python.exe'` (было `C:\karier\backend-v2\venv\…` — такого каталога нет) (`smoke.ps1:9`);
- файл остаётся в **UTF-8 с BOM** (обязательно для Windows PowerShell 5.1: без BOM кириллица ломает разбор — проверено парсером, `parse_errors=0`).

Сам smoke-прогон не запускался: нужен поднятый API на 8001 и `psql`; проверен только синтаксис скрипта.

### 2.5. Документация — пароля нет, есть ссылка на `.env`

| Файл | Что изменено |
|---|---|
| `docs/52-schema-builder-report.md:90-93` | вместо DSN с паролем — чтение `TEST_DATABASE_URL` из `tests/.env.test`, комментарий со ссылкой на `.env` |
| `docs/33-clean-slate-and-backup.md:68-70` | `$env:PGPASSWORD` вычисляется из `DATABASE_URL` в `backend-v2/.env`, в комментарии — ссылка на `.env` |
| `docs/team/01-backend-audit.md:255` | пароль заменён на `<redacted>` + пометка про `.env` (по разрешению капитана) |
| `docs/team/05-edit-review.md:149` | то же — `<redacted>` + ссылка на `.env` (по разрешению капитана) |

### 2.6. `.gitignore`

Добавлено (`.gitignore:6-7`, `:29`):

```gitignore
backend-v2/venv*/
*.broken-*

# Локальный DSN тестовой БД (с паролем) — не коммитится
backend-v2/tests/.env.test
```

Проверено: `git check-ignore -v` подтверждает `backend-v2/tests/.env.test` (`.gitignore:29`) и каталог `venv.broken-*` (`.gitignore:6`).

### 2.7. `.gitattributes` и коммит renormalize

Создан `.gitattributes`:

```
* text=auto eol=lf
*.ps1 text eol=crlf
*.cmd text eol=crlf
*.bat text eol=crlf
# + binary-маркеры для png/jpg/pdf/docx/xlsx/zip/woff/ttf/dump
```

Отдельный коммит `bf9fabe «chore(git): renormalize line endings»` — **маркерный**: `git add --renormalize` по 385 немодифицированным отслеживаемым файлам не дал изменений, потому что блобы в индексе уже LF (в установленном Git `core.autocrlf=true`, а `.gitattributes` снимает CRLF-шум: `git -c core.autocrlf=false status` показывает только реальные правки, без EOL-only). Это ожидаемо: политика EOL теперь зафиксирована, будущие коммиты CRLF не принесут. Если владельцу нужен именно «содержательный» renormalize-коммит — он появится при первом checkout/клоне с новыми атрибутами.

### 2.8. Удаление мусора

- `backend-v2/venv.broken-20261123-0911` — удалён (8 120 файлов, ~207 МБ), в `git status` больше не фигурирует;
- из индекса убраны скомпилированные `backend/app/__pycache__/*.pyc` (10 файлов, были отслеживаемыми; `__pycache__/` и так в `.gitignore`) — иначе `git add -A` тащил бы бинарь;
- каталоги `__pycache__` по проекту (14 шт., включая `backend-v2/app/core/__pycache__` с байткодом старого `config.py`, где лежал пароль) удалены — пересоберутся из чистых исходников.

---

## 3. Проверки (фактические результаты)

| Проверка | Команда | Результат |
|---|---|---|
| Пароль в отслеживаемых файлах | `git grep -l -P '<redacted_db_password>'` | **0** |
| Пароль в HEAD | `git grep -l -P '<redacted_db_password>' HEAD` | **0** |
| Пароль по рабочему дереву (без `.env*`) | тот же фильтр, что в verify-команде (`-notmatch 'node_modules\|\.git\\\|venv\|dist\|\.local\|backups\|\\\.env'`), прогнан побайтово по 37 789 файлам (ISO-8859-1, файлы < 20 МБ) | **matches=0** |
| Тесты | `backend-v2\venv\Scripts\python.exe -m pytest tests/test_auth_api.py -q` | **9 passed**, exit 0 |
| venv.broken | `git status --porcelain \| Select-String 'venv.broken'` | пусто; каталога на диске нет |
| `.env` не тронуты | `git status` по `.env` | пусто (файлы в ignore, содержимое/дата не менялись) |
| История | `git log --oneline -3` | `bf9fabe` renormalize → `b88b965` очистка → `efd3cd2` (прежний HEAD) |

Метод: прямой прогон `Select-String` по всему дереву на этой машине идёт десятки минут (крупные бинарники в `.npm-cache`/`.tmp`), поэтому тот же фильтр применён побайтовым сканом; дополнительно `Select-String` по `backend-v2` + `docs` + `src` + `src-v2` + `backend` (4,6 с) даёт **0** совпадений. `git grep` — 0 по рабочему дереву и по `HEAD`.

Ожидаемое исключение: `backend-v2/.env` (строка 7), `backend/.env` (старый прототип) и созданный `backend-v2/tests/.env.test` содержат **действующий** пароль — это служебные gitignored-файлы, их по контракту не трогаем; они уходят из оборота при ротации (S-1b/t9) и не попадут в новый приватный репозиторий.

---

## 4. Изменённые файлы

| Файл | Характер |
|---|---|
| `backend-v2/tests/conftest.py` | DSN из окружения/`.env.test`, fail-fast, без секрета |
| `backend-v2/app/core/config.py` | заглушки + prod-валидатор |
| `backend-v2/scripts/smoke.ps1` | пароль/TOTP из окружения/`.env`, путь к python, BOM |
| `backend-v2/tests/.env.test` | **новый, не трекается** (в `.gitignore`) |
| `.gitignore` | `backend-v2/venv*/`, `*.broken-*`, `.env.test` |
| `.gitattributes` | **новый**: EOL-политика |
| `docs/52-schema-builder-report.md` | без пароля, ссылка на `.env` |
| `docs/33-clean-slate-and-backup.md` | без пароля, ссылка на `.env` |
| `docs/team/01-backend-audit.md`, `docs/team/05-edit-review.md` | пароль → `<redacted>` |
| `docs/team/08-s1-repo-hygiene.md` | этот отчёт |

Не тронуты: `backend-v2/.env`, `backend/.env`, `backend-v2/app/main.py`, `app/services/gis.py`, `app/services/schema_snapshots.py`, `src-v2/**`.

В рабочем дереве остались **незакоммиченными** 19 изменённых и 18 новых файлов владельца (правки последнего спринта, `docs/team/*`, новые тесты, `docs/50…54`) — это осознанно: S-1 не коммитит чужую незавершённую работу. Они по-прежнему видны в `git status` и готовы к отдельному коммиту после ревью.

---

## 5. Что осталось владельцу

1. **Ротация пароля `karier_user`** — задача S-1b (t9): стоп API → `ALTER ROLE karier_user PASSWORD '<новый>'` → обновить `backend-v2/.env`, `backend-v2/tests/.env.test`, `C:\karier\.local\secrets\db-password.txt` → старт → `/api/health/ready`, вход, `pytest`.
2. **Новый приватный репозиторий + push** (действие владельца, `gh` не авторизован):
   ```powershell
   # после ротации и проверки; origin сейчас публичный github.com/Fonfond/karier-app
   git remote add private https://github.com/<owner>/<private-repo>.git
   git push private feature/sprint-29-maintenance-cables   # или main, по решению владельца
   ```
   До этого **не пушить в текущий `origin`**: в истории (`efd3cd2` и ранее) старый пароль всё ещё присутствует в блобах `config.py`, `smoke.ps1`, `docs/33`.
3. **Чистая история** (по плану S-1 п.6): новый репозиторий из «чистого» коммита либо `git filter-repo`, иначе старый пароль остаётся в истории (после ротации он уже не действует, но остаётся в старых клонах/форках публичного `origin`).
4. **По желанию:** убрать из индекса остальной мусор — `.vs/*` (6 файлов), `.vercel/*`, `src-v2/public/karier-map.jpg` (1 МБ, из аудита фронтенда), старый каталог `backend/` целиком.
5. **Авторство коммитов:** сейчас `backend-auditor (karier-improvements) <team@karier.local>` — при необходимости `git commit --amend --reset-author` перед push.
6. **Git в PATH:** portable MinGit лежит в `C:\karier\tools\MinGit`; для постоянной работы добавить `C:\karier\tools\MinGit\cmd` в `PATH` (или установить обычный Git for Windows).

---

## 6. Замечания и риски

- **BOM в `.ps1`**: Windows PowerShell 5.1 читает файлы без BOM как ANSI; кириллица в `smoke.ps1` ломала разбор (14 ошибок парсера). BOM восстановлен; при будущих правках `.ps1` редактором BOM сохранять (в `.gitattributes` BOM не управляется).
- **`.env.test` — файл с секретом на диске**: это осознанный компромисс (тестам нужен DSN). Он в `.gitignore`, но при копировании проекта/бэкапе каталога утекает. После S-1b в нём будет новый пароль; альтернатива — только `TEST_DATABASE_URL` в окружении.
- **`git add --renormalize` ничего не изменил** — не ошибка, а состояние индекса (см. §2.7); проверка `git -c core.autocrlf=false status` подтверждает, что EOL-шум снят.
- **`git grep` ищет по рабочему дереву/индексу**, не по всей истории: история до `b88b965` содержит старый пароль (см. §5.2-5.3).
- **`seed.py`** по-прежнему содержит демо-пароли `admin`/`operator123` (`seed.py:188,197`) — это тестовые учётки стенда, не секрет рабочей БД; менять их в S-1 не требовалось, но перед публичным репозиторием стоит перевести seed на пароли из `.env` (рекомендация).
