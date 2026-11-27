# S-1b: ротация пароля `karier_user` и проверка парольной аутентификации

**Дата:** 2026-11-25
**Исполнитель:** backend-auditor (задача t9, команда karier-improvements)
**Статус:** выполнено. Пароль ротирован, для `karier_user` включена проверка пароля (`scram-sha-256`), стек и тестовая БД проверены. Push не выполнялся, секрет в git не попадал.

---

## 1. Итог

| Что | Результат |
|---|---|
| Новый пароль | `secrets.token_urlsafe(24)` → **32 символа** (≥24), только `[A-Za-z0-9_-]` — безопасен в SQL-литерале и в URL |
| Где лежит | `C:\karier\.local\secrets\db-password.txt` (каталог вне git; ACL снят с наследования, доступ только текущему пользователю) |
| `ALTER ROLE` | применён; SCRAM-хэш роли изменился (было/стало — разные, 133 символа) |
| pg_hba | для `karier_user` с `127.0.0.1/32` и `::1/128` включён `scram-sha-256` **выше** общего `trust`; выполнен `pg_reload_conf()` |
| Проверка «неверный пароль» | `psql postgresql://karier_user:definitely-wrong-password@127.0.0.1:5432/karier_test_db` → **exit 2**, `FATAL: password authentication failed for user "karier_user"` |
| Проверка «новый пароль» | `PGPASSWORD=<new> psql -h 127.0.0.1 -U karier_user -d karier_db` → **exit 0**, `current_database() = karier_db` |
| Суперпользователь | `psql -U postgres` по-прежнему работает (правило `trust` для остальных не менялось) |
| Стек | `GET /api/health/ready` → `database: ok`; вход `000001/admin` → 200 с токеном; карта (`/api/map/layers/active`) и схема (`/api/topology/graph`) открываются |
| Тестовая БД | `C:\karier\test-db-reset.cmd` → собрана: 4700 objects / 3788 links / 17 blocks / 87 employees / 18 types / alembic `0014_schema_snapshots` |
| Тесты | `pytest tests/test_auth_api.py tests/test_schema_builder.py` → **16 passed** (прогон выполнен до запроса QA «не запускать pytest»; после — не повторялся) |
| Секрет в git | `git grep` нового пароля → 0; `.env`, `.env.test`, `.local` — в ignore/вне репозитория |

---

## 2. Что сделано (по шагам)

### 2.1. Пароль

```powershell
# генерация (32 символа)
C:\karier\karier\backend-v2\venv\Scripts\python.exe -c "import secrets;print(secrets.token_urlsafe(24))"
# сохранение вне репозитория + ACL
New-Item -ItemType Directory -Force C:\karier\.local\secrets
# ... Set-Content C:\karier\.local\secrets\db-password.txt
icacls C:\karier\.local\secrets\db-password.txt /inheritance:r /grant:r "$env:USERNAME:R"
```

Значение пароля в отчёте и в переписке не приводится — только путь.

### 2.2. Остановка API и `ALTER ROLE`

Остановлен только API (PostgreSQL и Vite продолжали работать, чтобы не было полного простоя):
`Stop-Process` для uvicorn (parent 29304 + listener 30296) → порт 8001 свободен.

SQL передан в `psql` через stdin (`-f -`), чтобы пароль не попал в командную строку/историю:

```powershell
$sql = "ALTER ROLE karier_user PASSWORD '" + $new + "';"
$sql | & 'C:\karier\.local\pg18\vendor\pgsql\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f -
```

Контроль: `select rolpassword from pg_authid where rolname='karier_user'` до и после — хэш изменился (SCRAM-SHA-256).

### 2.3. Обновление окружения

- `backend-v2/.env`: `DATABASE_URL` → новый пароль (UTF-8 без BOM, остальные строки не тронуты);
- `backend-v2/tests/.env.test`: `TEST_DATABASE_URL` → новый пароль (файл в `.gitignore`, в git не попадает; шаблон в комментарии сохранён с `<password>`).

Проверка: `from app.core.config import settings` + `create_engine(settings.DATABASE_URL)` → `select current_database()` = `karier_db`.

### 2.4. `pg_hba.conf`: проверка пароля вместо `trust`

Файл: `C:\karier\.local\pg18\data\pg_hba.conf` (вне репозитория). Перед общим правилом `trust` добавлено (строки 119–121):

```
# S-1b: karier_user checks password via scram-sha-256 (rule above generic trust)
host    all             karier_user    127.0.0.1/32            scram-sha-256
host    all             karier_user    ::1/128                 scram-sha-256
```

- порядок важен: hba применяет **первое** подходящее правило, поэтому специфичное правило для `karier_user` стоит выше `host all all 127.0.0.1/32 trust`;
- вторая колонка — база (`all`: и `karier_db`, и `karier_test_db`, и будущие);
- reload: `select pg_reload_conf();` → `t`;
- контроль синтаксиса: `select line_number, error from pg_hba_file_rules where error is not null` → пусто; активные правила: `120 | {all} | {karier_user} | 127.0.0.1 | scram-sha-256`, `121 | … | ::1 | scram-sha-256`;
- `trust` для `postgres` и остальных ролей не менялся — суперпользователь и `psql -U postgres` в скриптах (`test-db-reset`, `db-backup`) работают как раньше.

### 2.5. Перезапуск стека и приёмка

`C:\karier\.local\stack.ps1 start` (API поднят, PG и Vite уже слушали) → `/api/health/ready` = `ok`, вход `000001/admin` = 200, `/api/map/layers/active` = 200, `/api/topology/graph` = 200.

### 2.6. `reset-test-db.ps1`

`C:\karier\.local\reset-test-db.ps1:30` содержал старый DSN в `$TestUrl`. Теперь пароль читается из `C:\karier\.local\secrets\db-password.txt`:

```powershell
$SecretFile = 'C:\karier\.local\secrets\db-password.txt'
if (-not (Test-Path $SecretFile)) { throw "Не найден ${SecretFile}: пароль роли karier_user хранится вне репозитория" }
$DbPassword = (Get-Content -Raw $SecretFile).Trim()
$TestUrl = "postgresql+psycopg://karier_user:${DbPassword}@127.0.0.1:5432/$TestDb"
```

Файл остаётся UTF-8 **с BOM** (Windows PowerShell 5.1 иначе ломает разбор кириллицы), синтаксис проверен парсером: 0 ошибок.
`C:\karier\test-db-reset.cmd` прогнан: `karier_test_db` пересобрана (4700 objects / 3788 links / 17 blocks / 87 employees / 18 types / 0014), exit 0. Предупреждения `pg_dump` про `--disable-triggers` — ожидаемые для data-only restore.

---

## 3. Инцидент по ходу работы (и как исправлен)

**Что произошло.** При первой правке `pg_hba.conf` строки были записаны с четырьмя полями вместо пяти (пропущена колонка `DATABASE`): `host karier_user 127.0.0.1/32 scram-sha-256`. PostgreSQL не смог разобрать файл (`end-of-line before authentication method`, строки 120–121) и отклонял **все новые** подключения с `FATAL: could not load …/pg_hba.conf`. Окно — около 2–3 минут.

**Последствия.** API продолжал обслуживать запросы на уже открытых соединениях пула; в `C:\karier\.local\logs\api.log` за это окно нет ни `password authentication failed`, ни `OperationalError`, ни 500. Новые подключения (в т.ч. psql) в это окно не проходили.

**Исправление.** Строки удалены (файл вернулся к рабочему виду, соединения восстановились), затем правило добавлено в корректном виде (5 полей, колонка `all`) и проверено через `pg_hba_file_rules` **до** боевой проверки. Пароль при этом не откатывался: он уже был ротирован, откат не требовался.

**Вывод на будущее:** `pg_hba.conf` править только с проверкой `pg_hba_file_rules.error` сразу после записи; в репозиторий файл не входит (живёт в `.local`), поэтому изменение нужно повторить при переустановке стенда/на новом сервере.

---

## 4. Откат (если понадобится)

Все артефакты отката — в `C:\karier\.local\backups\rotation-20261124\` (вне git):

| Файл | Что это |
|---|---|
| `env.before-rotation.bak` | `backend-v2/.env` до ротации (старый пароль) |
| `env.test.before-rotation.bak` | `backend-v2/tests/.env.test` до ротации |
| `pg_hba.conf.after` | hba после включения `scram-sha-256` (для сравнения/восстановления) |

Порядок отката:

1. Вернуть пароль роли (значение — из `env.before-rotation.bak`, строка `DATABASE_URL`):
   ```powershell
   $old = ((Get-Content -Raw C:\karier\.local\backups\rotation-20261124\env.before-rotation.bak) -split '://')[1].Split(':')[1].Split('@')[0]
   "ALTER ROLE karier_user PASSWORD '$old';" | & 'C:\karier\.local\pg18\vendor\pgsql\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f -
   ```
2. Убрать из `C:\karier\.local\pg18\data\pg_hba.conf` три добавленные строки (комментарий + два `host … karier_user … scram-sha-256`) и выполнить reload:
   ```powershell
   & 'C:\karier\.local\pg18\vendor\pgsql\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgres -c "select pg_reload_conf();"
   ```
3. Восстановить `backend-v2/.env` и `backend-v2/tests/.env.test` из бэкапов (или вписать старый пароль вручную).
4. Перезапустить API: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\karier\.local\stack.ps1 restart`; проверить `/api/health/ready` и вход.
5. Удалить бэкапы `rotation-20261124` после подтверждения, что откат не нужен (в них лежит старый пароль).

---

## 5. Известные ограничения и что осталось

1. **Легаси `C:\karier\karier\backend\.env`** (v1, untracked, в `.gitignore`) содержит **старый** пароль. По указанию капитана файл не тронут — зафиксировано как известное. Рекомендация: удалить каталог `backend/` (v1 выведен из работы) или вычистить его `.env` при общей уборке.
2. **История git**: старый пароль остаётся в блобах коммитов до `efd3cd2` (в т.ч. в `backend-v2/app/core/config.py`, `scripts/smoke.ps1`, `docs/33` тех ревизий). После ротации он недействителен, но при публикации репозитория историю нужно сделать чистой (новый приватный репозиторий с чистого коммита либо `git filter-repo`).
3. **Приватный remote и push** — действие владельца: текущий `origin` = публичный `github.com/Fonfond/karier-app`; push не выполнялся.
4. **`pg_hba.conf` вне репозитория**: при переносе стенда/Docker (F-1) проверку пароля для `karier_user` нужно настроить в конфиге PostgreSQL заново; в Docker `trust` недопустим.
5. **`trust` для остальных ролей** на стенде оставлен как был (чтобы не сломать `postgres`-скрипты). Для продакшена — отдельная задача: перевести и `postgres` на `scram-sha-256`/`peer`.
6. **Секрет на диске**: `db-password.txt` + rollback-бэкапы со старым паролем. После приёмки старые бэкапы удалить; новый пароль передать владельцу в сейф/менеджер секретов.
7. **QA-приёмка**: по просьбе капитана финальный `pytest` и `test-db-reset` повторно не запускались (QA выполняет V1 и сбрасывает тестовую БД). Ранее полученные результаты: reset exit 0, `16 passed`.

---

## 6. Проверки (сводка)

| Проверка | Результат |
|---|---|
| `GET /api/health/ready` | `ready=ok` |
| `python -c … settings.DATABASE_URL …` | `karier_db` (exit 0) |
| `psql 'postgresql://karier_user:definitely-wrong-password@…/karier_test_db'` | exit 2, `FATAL: password authentication failed` |
| `PGPASSWORD=<new> psql -U karier_user -d karier_db` | exit 0, `karier_db` |
| `psql -U postgres` | `pg-ok` |
| `C:\karier\test-db-reset.cmd` | exit 0, 4700/3788/17/87/18/0014 |
| `pytest tests/test_auth_api.py tests/test_schema_builder.py` | 16 passed (до «стоп» от QA) |
| Вход `000001/admin`, карта, схема | 200 |
| `git grep <new>` | 0 |
| Старый пароль в рабочем дереве | только `backend/.env` (легаси, известно) |
