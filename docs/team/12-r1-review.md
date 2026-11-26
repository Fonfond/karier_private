# 12 — R1: ревью ротации пароля и гигиены репозитория (S-1 / S-1b)

**Дата:** 2026-11-25, 06:50–12:10 (локальное время машины, UTC+08:00)
**Кто:** `integrator` (задача t11, команда `karier-improvements`), ревью независимо от исполнителя
(`backend-auditor`, задачи t7 и t9).
**Предмет:** S-1 — очистка секретов и гигиена репозитория (`docs/team/08-s1-repo-hygiene.md`),
S-1b — ротация пароля `karier_user` (`docs/team/10-s1b-rotation.md`), с опорой на приёмку V1
(`docs/team/11-v1-acceptance.md`).
**Характер работ:** только чтение и проверки. Код, тесты, конфиги, `.env*`, `pg_hba.conf` и секреты
не изменялись; стек не перезапускался; пароль повторно не ротировался; коммитов и `push` нет.
Записан один файл — этот отчёт. Единственные действия с побочным эффектом описаны в §6.3.

---

## 1. Вердикт

**`pass`** — ротация и очистка секретов выполнены безопасно и подтверждаются независимыми
измерениями. Секретов в отслеживаемых файлах и в индексе нет, новый пароль существует только вне
git, приложение работает на новом пароле, тесты зелёные, `push` в публичный `origin` не выполнялся
(на GitHub лежит только исходный прототип из 2 коммитов, без `backend-v2`). План возврата описан и
подкреплён бэкапами.

Блокирующих находок нет. Семь замечаний (все `low`/`info`) — остатки гигиены и операционные
хвосты, они не мешают приёмке и не требуют повторной ротации. Сводка: §5.

| Критерий приёмки | Итог | Ключевое доказательство |
|---|---|---|
| Нет секретов в отслеживаемых файлах (DSN/пароль/токены) | **PASS** | `git grep` по worktree / HEAD / индексу: старый и новый пароль — 0; побайтовый скан 436 файлов (4,2 МБ) без `.env*` — 0; сканы 1 zip-архива (docx) и `dist` — 0 |
| Новый пароль не встречается в индексе и в `docs/` | **PASS** | `git grep <new>` по индексу, HEAD и worktree — 0; `git log --all -S<new>` — 0 коммитов; скан `docs/**` — 0 |
| Приложение работает после ротации: health, вход, граф | **PASS** | `/health/live` 200, `/health/ready` 200 `database: ok`, вход `000001` 200 (role=admin, токен 321 симв.), `/topology/graph` 200 (nodes=1, links=0), `/map/layers/active` 200, без токена 401 |
| Тесты зелёные | **PASS** | Независимый поднабор `test_auth_api` + `test_api_contract_validation` + `test_schema_snapshots` = **19 passed**, exit 0, 28,5 с; полный набор — 173 passed ×2 в V1 на сброшенной тестовой БД |
| Описанный план возврата при откате ротации | **PASS** | `10` §4: 5 шагов + 3 бэкапа в `C:\karier\.local\backups\rotation-20261124\`; бэкапы на месте и содержат старый пароль (проверено) |
| Нет `push` в remote с секретами | **PASS** | `git ls-remote origin` → только `refs/heads/main = 5d930c5`; на remote 2 коммита прототипа и **0** файлов `backend-v2/`; коммит с паролем `1463fe5` не является предком `origin/main`; у текущей ветки нет upstream |

---

## 2. Что именно проверялось (независимо от отчётов исполнителя)

1. **Секреты в git-областях.** `git grep` по рабочему дереву (только отслеживаемые файлы), по `HEAD`,
   по индексу (`--cached`) и по дереву `refs/remotes/origin/main`; pickaxe `git log --all -S<pw>`
   по всей истории (57 коммитов, 31 локальная ветка).
2. **Секреты на диске.** Побайтовый скан дерева репозитория и `C:\karier\.local\logs` (436 файлов,
   4,2 МБ; исключены `.git`, `node_modules`, `venv*`, `dist`, `backups`, `__pycache__`, бинарные
   расширения; `.env*` учтены отдельно). Скан содержимого zip/Office-архивов (XML внутри) и
   собранного `src-v2/dist`.
3. **Хранение нового пароля.** `C:\karier\.local\secrets\db-password.txt` (вне репозитория), ACL файла;
   содержимое `backend-v2/.env` и `backend-v2/tests/.env.test` (сравнение значений, без вывода);
   правила `git check-ignore` и `git ls-files` для `.env*`.
4. **База.** Прямая аутентификация `psql` новым, старым и случайным паролем; `pg_hba_file_rules`
   (активные правила и ошибки), тип хэша роли, read-only `count(*)` на `karier_db`.
5. **Приложение.** Живые HTTP-запросы к `127.0.0.1:8001` (health/live, health/ready, login, graph,
   map/layers/active, graph без токена); корреляция времени старта процесса API с mtime `.env` и
   временем создания соединений в `pg_stat_activity`.
6. **Тесты.** Свой прогон поднабора на `karier_test_db` через `tests/.env.test` (то есть проверен и
   новый DSN, и работоспособность conftest после S-1).
7. **Remote.** `git remote -v`, `for-each-ref refs/remotes`, `packed-refs`, upstream ветки,
   `git ls-remote --heads origin` (сетевой запрос), reflog `HEAD`.
8. **План откатa.** Наличие и содержимое бэкапов ротации, корректность шагов `10` §4 относительно
   фактических имён файлов и правил `pg_hba`.

Ограничения метода — §6.1.

---

## 3. Секреты: git-области и диск

### 3.1. Отслеживаемые файлы, индекс, HEAD, история

| Область | Старый пароль БД | Новый пароль БД | Dev-`SECRET_KEY` из старого `config.py` |
|---|---|---|---|
| Рабочее дерево (tracked) | 0 | 0 | 0 |
| `HEAD` (`bf9fabe`) | 0 | 0 | 0 |
| Индекс (`--cached`) | 0 | 0 | 0 |
| Дерево `origin/main` | 0 | 0 | 0 |
| История `--all` (pickaxe) | **4 коммита**: `1463fe5`, `bf3eb5a`, `07d7534` — и удаление в `b88b965` | **0** | 3 коммита, удаление в `b88b965` |

Старый пароль в текущих файлах отсутствует полностью, включая `app/core/config.py`,
`scripts/smoke.ps1`, `docs/33`, `docs/52` — в них теперь заглушки/чтение из `.env`:
`config.py:13-14,34,42` (`__SET_DB_PASSWORD__`, `__SET_SECRET_KEY__` + prod-валидатор `:98-110`),
`docs/33:69` и `docs/52:91` («пароль в документации не хранится»).

Единственные DSN с «паролем» в отслеживаемых файлах — заведомые примеры:
`backend-v2/.env.example:10` (`user:password@…`) и `README.md:90` (`user:pass@…`). Литеральных
`SECRET_KEY`/приватных ключей/токенов (`ghp_`, `sk-`, `VERCEL_BLOB_TOKEN=<value>`) в индексе нет.

**Вывод по истории:** старый пароль остаётся в блобах коммитов до `b88b965` (это документировано в
`10` §5.2 и `08` §5.2-5.3). Он **не опубликован** (§4) и **уже недействителен** (§3.3), поэтому
риск — только при будущей публикации истории; отсюда находка R1-03.

### 3.2. Диск и хранение нового пароля

- Побайтовый скан: **0** совпадений старого пароля, нового пароля и dev-ключа в 436 текстовых файлах
  репозитория (включая `docs/team/*.md`, `docs/50-54`, `src-v2/dist`, `C:\karier\.local\logs\api.log`).
- Архивы: 1 zip-подобный документ (`docs/50-tz-as-built-and-report.docx`) — 0 совпадений по XML-частям.
- `.env*` (ожидаемо, gitignored): `backend-v2/.env` и `backend-v2/tests/.env.test` содержат **только
  новый пароль** (сравнение значений: `eq_new=True`, `eq_old=False`, длина 32); `backend/.env`
  (легаси v1) содержит **старый** пароль — R1-02.
- Новый пароль: 32 символа, `secrets.token_urlsafe(24)`, вне репозитория —
  `C:\karier\.local\secrets\db-password.txt`, ACL файла без наследования: единственная запись —
  `DESKTOP-…\<текущий пользователь>:(R)`. Каталог `.local\secrets` при этом наследует права
  (Users: RX — видно имя файла, но не содержимое) — R1-06.
- `git ls-files` → только `backend-v2/.env.example`; `git check-ignore -v` подтверждает
  `.gitignore:25` для `.env`, `.gitignore:29` для `tests/.env.test`, `.gitignore:47` для `backend/.env`.
- Скрипты в `.local` (`reset-test-db.ps1`, `stack.ps1`, `run-api.cmd`, `run-web.cmd`) литералов пароля
  не содержат: `reset-test-db.ps1` читает `db-password.txt` (как заявлено в `10` §2.6).

### 3.3. Пароль как учётные данные: ротация состоялась

| Проверка | Команда | Результат |
|---|---|---|
| Новый пароль | `PGPASSWORD=<new> psql -h 127.0.0.1 -U karier_user -d karier_db -tAc "select current_database(), current_user"` | **exit 0**, `karier_db|karier_user` |
| Старый пароль | `PGPASSWORD=<old> psql … karier_db` | **exit 2**, `FATAL: password authentication failed for user "karier_user"` |
| Случайный пароль (контроль) | `PGPASSWORD=definitely-wrong-password psql …` | **exit 2**, `FATAL: password authentication failed` |
| Хэш роли | `select rolpassword from pg_authid where rolname='karier_user'` | `SCRAM-SHA-256` |
| `pg_hba` для роли | `select line_number, database, user_name, address, auth_method, error from pg_hba_file_rules` | строки **120** `all | karier_user | 127.0.0.1 | scram-sha-256`, **121** `::1 | scram-sha-256`, `error` — пусто; общий `trust` (стр. 122/124) остаётся для прочих ролей |
| Рабочая БД | read-only `select count(*) from gis.assets` (postgres) | 1 — согласуется с «clean slate» из V1 |

То есть проверка пароля для `karier_user` действительно включена и стоит **выше** общего `trust`, а
старый пароль отозван на уровне роли.

---

## 4. Remote: push с секретами не выполнялся

| Проверка | Результат |
|---|---|
| `git remote -v` | `origin = https://github.com/Fonfond/karier-app.git` (публичный) |
| `git ls-remote --heads origin` | **только** `refs/heads/main = 5d930c5` |
| Содержимое `origin/main` | 2 коммита: `c91b67e Initial commit`, `5d930c5 Working prototype: basic map, login, offline sync`; файлов `backend-v2/` — **0** |
| `git merge-base --is-ancestor 1463fe5 refs/remotes/origin/main` | exit 1 — коммит с паролем **не** предок remote |
| Upstream текущей ветки | нет (`fatal: no upstream configured for branch 'feature/sprint-29-maintenance-cables'`) |
| Локальные ветки на remote | 31 ветка локально, ни одной `refs/remotes/origin/*` кроме `main` |
| `git log --oneline -3` | `bf9fabe`, `b88b965`, `efd3cd2` — два новых коммита только локально |
| `.git/logs/HEAD` (reflog) | только локальные операции (commits/amend), следов fetch/push нет |

**Вывод:** публичный `origin` содержит исходный прототип от 2026-11-03 и не содержит ни
`backend-v2`, ни коммитов с паролем. Утечки старого пароля через remote не было. Задача
«приватный remote и push» остаётся за владельцем (так и зафиксировано в `10` §5.3).

---

## 5. Приложение после ротации

| Проверка | Результат |
|---|---|
| `GET /api/health/live` | **200** `{"status":"ok"}` |
| `GET /api/health/ready` | **200** `{"status":"ok","service":"karier-api","version":"0.1.0","database":"ok"}` |
| `POST /api/auth/login` `{"tab_no":"000001","password":"admin"}` | **200**, `role=admin`, `tab_no=000001`, `access_token` 321 симв., `mfa_required=false`, `must_change_password=true` |
| `GET /api/topology/graph` без токена | **401** (RFC 7807: `auth.unauthorized`, `request_id` присутствует) |
| `GET /api/topology/graph` с Bearer | **200**, 5 586 байт, `nodes=1`, `links=0`, `blocks=1` — совпадает с «clean slate» в V1 |
| `GET /api/map/layers/active` с Bearer | **200**, 284 байта |
| Процесс API | pid 9968, старт **2026-11-24 22:20:11**; `.env` записан **22:19:56**, `.env.test` — **22:20:05** → процесс поднят уже с новым DSN |
| Новые соединения приложения к `karier_db` | `pg_stat_activity`: 1 соединение с 2026-11-24 22:20:15 (стартовый пул) и **3 соединения с 2026-11-25 09:50:13**, созданные уже после включения `scram-sha-256` (правило активно с ~09:18) → пароль принимается именно новым значением |
| Ошибки в логе | `api.log` (100 КБ): `password authentication failed`, `OperationalError`, `FATAL`, `Traceback` — **0** совпадений |

Дополнительно: `backend-v2\.env` содержит dev-`SECRET_KEY` (прежний dev-ключ из `config.py`, длина 37,
значение в отчёте не приводится) и `EXPOSE_OTP_CODE=true` — это состояние стенда, не регресс
S-1/S-1b (см. §7 и R1-04).

**Тесты (независимый прогон).** `pytest tests/test_auth_api.py tests/test_api_contract_validation.py
tests/test_schema_snapshots.py -q` → **19 passed**, 0 failed, 492 warning, 28,49 с, exit 0. Прогон шёл
через `tests/.env.test` — то есть проверены и новый пароль, и fail-fast conftest после S-1. Полный
набор в V1: 173 passed ×2 (477,1 с и 425,4 с) после канонического сброса тестовой БД. Оговорка о
неизоляции тестов (S-9) остаётся, к S-1/S-1b отношения не имеет.

**План возврата.** `10` §4 описывает 5 шагов (вернуть пароль роли из `env.before-rotation.bak` →
убрать 3 строки из `pg_hba.conf` + reload → восстановить `.env`/`.env.test` → `stack.ps1 restart` →
проверить ready/вход → удалить бэкапы). Артефакты на месте:
`env.before-rotation.bak` (содержит **только** старый пароль, проверено), `env.test.before-rotation.bak`
(старый), `pg_hba.conf.after`. Шаги согласуются с фактическим путём `pg_hba.conf`
(`C:\karier\.local\pg18\data\pg_hba.conf`) и с доступом `postgres` по `trust` (строки 117/122/124),
поэтому откат выполним без остановки PostgreSQL.

---

## 6. Находки

Серьёзность: **blocker / high / medium / low / info**. Ни одна не блокирует приёмку S-1/S-1b;
`requiredFix` — минимальное действие, не требующее повторной ротации.

| ID | Сер. | Проблема | Файл/место | Минимальная правка (requiredFix) |
|---|---|---|---|---|
| **R1-01** | low | В индексе остаются 8 служебных файлов IDE/Vercel: `.vercel/README.txt`, `.vercel/project.json`, `.vs/ProjectSettings.json`, `.vs/VSWorkspaceState.json`, `.vs/karier-app/FileContentIndex/*.vsidx`, `.vs/karier-app/v17/.wsuo`, `.vs/karier-app/v17/DocumentLayout.json`, `.vs/slnx.sqlite` (бинарный). `.gitignore` не содержит `.vs/` и `.vercel/` (есть только `.vscode/`), поэтому они вернутся при `git add -A`. Секретов в них нет (скан чист), но `.vs/slnx.sqlite`/`.wsuo` — машинно-зависимые бинарники. Исполнитель это зафиксировал (`08` §5.4, «по желанию»), то есть не скрыто. | `.gitignore`, индекс | Отдельный коммит: `git rm -r --cached .vs .vercel`; добавить в `.gitignore` строки `.vs/` и `.vercel/`; проверить `git status --porcelain` (должно исчезнуть 8 записей) |
| **R1-02** | low | Старый (уже недействительный) пароль остаётся на диске: `backend\.env` легаси v1 и три бэкапа ротации в `C:\karier\.local\backups\rotation-20261124\`. В git не попадает (`.env` в ignore, `.local` вне репозитория), но `backend/` — это v1, который всё ещё можно задеплоить (F §1.3, I-40), и он несёт мёртвый секрет рядом с живым проектом. | `backend\.env`; `.local\backups\rotation-20261124\*` | После приёмки: удалить бэкапы ротации (п.5 плана `10` §4); по `backend/` — решение владельца (I-40): удалить каталог v1 либо обнулить его `.env`. Ротация не требуется: старый пароль отклоняется (exit 2) |
| **R1-03** | low | Старый пароль БД и dev-`SECRET_KEY` остаются в **локальной** истории git (коммиты `1463fe5`, `bf3eb5a`, `07d7534`; удалены в `b88b965`). На remote не публиковались (§4), пароль мёртв (§3.3). Риск реализуется только если эту историю опубликовать как есть (или склонировать её в публичный репозиторий). | история git | Не пушить текущую историю в публичный remote. Для публикации — новый репозиторий с чистого коммита либо `git filter-repo --replace-text` (уже в плане `10` §5.2, `08` §5.3). После выбора — зафиксировать в `docs/54` |
| **R1-04** | low | Демо-пароли стендовых учёток остаются в отслеживаемом коде: `seed.py` (`admin`/`operator123`, см. `08` §6) и тесты/док `docs/54` используют `operator123`. Это не секрет рабочей БД (роль `karier_user` ротирована), но при публикации репозитория пароли стенда становятся публичными. Относится к I-06, не к S-1. | `backend-v2\app\seed.py`, тесты, `docs/54` | В рамках I-06: seed выдаёт одноразовый пароль (печатает в консоль) или берёт из `.env`; тесты — из фикстуры/`KARIER_TEST_PASSWORD`. До этого — не публиковать репозиторий вместе с seed-паролями либо сменить их на стенде |
| **R1-05** | info | Коммит `bf9fabe «chore(git): renormalize line endings»` **пустой**: `git show --stat` не содержит изменённых файлов (renormalize не дал эффекта, EOL-политика зафиксирована в `b88b965`). Сообщение обещает больше, чем содержит коммит; в истории это «маркер». Исполнитель описал причину (`08` §2.7). | история git | Оставить как есть (безвредно) либо при переписывании истории перед публикацией объединить с `b88b965`; в release notes указать, что renormalize — политика, а не перезапись блобов |
| **R1-06** | info | Новый пароль лежит в двух служебных файлах на диске: `backend-v2\.env` и `backend-v2\tests\.env.test` (оба gitignored) — по контракту S-1 так и задумано. Дополнительно каталог `.local\secrets` наследует права (`Users: RX`), т.е. имя файла видно всем локальным пользователям (содержимое — нет, ACL файла ограничен). | `.env`, `.env.test`, `.local\secrets` | Принять для стенда. Для CI/переноса — передавать `TEST_DATABASE_URL`/`DATABASE_URL` только через окружение; после приёмки — снять наследование и с каталога `.local\secrets` (`icacls … /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"`) |
| **R1-07** | info | Авторство коммитов — служебное (`backend-auditor (karier-improvements) <team@karier.local>`). Для истории владельца это выглядит чужеродно; исполнитель это отметил (`08` §2.1, §5.5). | коммиты `b88b965`, `bf9fabe` | Перед публикацией — `git commit --amend --reset-author` (для двух коммитов: `git rebase --exec 'git commit --amend --reset-author --no-edit' b88b965^..HEAD`) либо принять служебное авторство |

**Наблюдения вне предмета ревью** (не влияют на вердикт, уже в бэклоге):
`must_change_password=true` не мешает входу и выдаче токена — известный разрыв I-06 (проверено на
`000001`: login 200 при `must_change=true`); OTP-код по-прежнему может попадать в лог при
`EXPOSE_OTP_CODE=true` (I-02, в текущем `api.log` 6-значных кодов нет — 5 совпадений оказались
фрагментами UUID); дрейф Alembic (29 предсуществующих операций) — S-10; неизоляция тестов и
data-flake `test_registration_flow` — S-9; дампы рабочей БД (2 × ~372 МБ) лежат в `karier\backups`
(ignored) — R22 из ревью правок.

---

## 7. Что ревью не проверяло (ограничения)

1. **Содержимое бинарных дампов** `backups\*.dump` (2 × ~372 МБ) и `pg18\data` не распаковывалось:
   в дампах — данные и хэши паролей сотрудников, а не пароль роли БД; это предсуществующая проблема
   R22 (дампы внутри проекта), не результат S-1.
2. **История до `b88b965`** проверена pickaxe-поиском по всем 57 коммитам и 31 ветке; полный
   позаблочный обход не делался (не требуется: pickaxe покрывает все блобы всех коммитов).
3. **Побайтовый скан** покрыл 436 текстовых файлов (4,2 МБ) с исключением `.git`, `node_modules`,
   `venv*`, `dist`, `backups`, `__pycache__` и бинарных расширений; `src-v2\dist` и docx проверены
   отдельно (0). `node_modules`/`venv` сторонним кодом считаются нерелевантными.
4. **Полный `pytest` повторно не запускался** (нужен сброс тестовой БД, ~7 мин + известная
   неизоляция): независимо прогнан поднабор 19 тестов, полный набор взят из V1 (173 passed ×2).
5. **Стек не перезапускался** и пароль не ротировался повторно: проверялось фактическое состояние
   (процесс, соединения, прямой `psql`), а не процедура «с нуля».
6. **Сетевой доступ к GitHub** ограничился одним `git ls-remote --heads` (20 с, ответ получен);
   содержимое remote-репозитория сверялось по этому ответу и по `refs/remotes/origin/main`.
7. **Побочные эффекты проверок:** (а) один вход через API (`000001`) создал сессию и запись аудита в
   `karier_db` — это требует критерий «вход» и повторяет проверку V1; (б) прогон поднабора оставил
   данные в `karier_test_db` (известная неизоляция, S-9); (в) в `C:\karier\.local` созданы два
   вспомогательных read-only скрипта сканирования (`scan-secrets-review.py`, `scan-archives-review.py`),
   оба вне репозитория, в отчётах и коде не используются.

---

## 8. Приложение: сводка команд (без значений секретов)

```powershell
# git (portable MinGit 2.47.1)
git -C C:\karier\karier log --oneline -3                     # bf9fabe, b88b965, efd3cd2
git -C C:\karier\karier remote -v                            # origin = публичный GitHub
git -C C:\karier\karier for-each-ref refs/remotes            # только origin/main = 5d930c5
git -C C:\karier\karier ls-remote --heads origin             # main = 5d930c5
git -C C:\karier\karier merge-base --is-ancestor 1463fe5 refs/remotes/origin/main   # exit 1
git -C C:\karier\karier grep -F -n -e <OLD_PW> -- . ; --cached ; HEAD ; refs/remotes/origin/main
git -C C:\karier\karier log --all --oneline -S <OLD_PW>      # 4 коммита (удалён в b88b965)
git -C C:\karier\karier log --all --oneline -S <NEW_PW>      # 0
git -C C:\karier\karier check-ignore -v backend-v2/.env backend-v2/tests/.env.test backend/.env
git -C C:\karier\karier ls-files                             # 404 файла; .env* — только .env.example

# секреты на диске
python C:\karier\.local\scan-secrets-review.py               # 436 файлов / 4,2 МБ: old=0 new=0 devkey=0
python C:\karier\.local\scan-archives-review.py              # 1 архив: 0

# база
psql -h 127.0.0.1 -U karier_user -d karier_db -tAc "select current_database(), current_user"  # new: exit 0
psql -h 127.0.0.1 -U karier_user -d karier_db -tAc "select 1"                                  # old/random: exit 2
psql -h 127.0.0.1 -U postgres -d postgres -tAc "select line_number, array_to_string(database,','), array_to_string(user_name,','), coalesce(address::text,'-'), auth_method, coalesce(error,'-') from pg_hba_file_rules order by line_number"
psql -h 127.0.0.1 -U postgres -d postgres -tAc "select rolname, left(rolpassword,13) from pg_authid where rolname='karier_user'"
psql -h 127.0.0.1 -U postgres -d postgres -tAc "select pid, datname, state, to_char(backend_start,'YYYY-MM-DD HH24:MI:SS') from pg_stat_activity where usename='karier_user'"

# приложение и тесты
Invoke-WebRequest http://127.0.0.1:8001/api/health/ready          # 200 database=ok
Invoke-WebRequest -Method Post http://127.0.0.1:8001/api/auth/login -Body '{"tab_no":"000001","password":"admin"}' -ContentType 'application/json'   # 200
Invoke-WebRequest http://127.0.0.1:8001/api/topology/graph       # 401 без токена / 200 с Bearer
cd C:\karier\karier\backend-v2; .\venv\Scripts\python.exe -m pytest tests/test_auth_api.py tests/test_api_contract_validation.py tests/test_schema_snapshots.py -q   # 19 passed
```
