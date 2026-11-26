# 16 — S-1c: гигиена индекса, авторство коммитов, удаление бэкапов ротации

**Дата:** 2026-11-25, 11:50–12:05 (локальное время машины, UTC+08:00)
**Кто:** `integrator` (задача t28, команда `karier-improvements`)
**Основание:** находки ревью R1 (`docs/team/12-r1-review.md`): R1-01 (`.vs/`, `.vercel/` в индексе),
R1-02 (бэкапы ротации со старым паролем), R1-07 (служебное авторство коммитов). R1-03 (старый пароль
в локальной истории) и R1-04 (seed-пароли) решением капитана оставлены владельцу / волне 2; R1-05
(пустой коммит renormalize) и R1-06 (ACL `.local\secrets`) приняты как есть.
**Рамки:** `push` не выполнялся, remote не добавлялся, `backend-v2/.env` и `backend/.env` не
изменялись, `karier_db` не затрагивалась. Изменены только `.gitignore` и этот отчёт; в git-индексе
сняты 8 служебных файлов (на диске они остаются).

---

## 1. Итог

| Что | Было | Стало |
|---|---|---|
| HEAD ветки `feature/sprint-29-maintenance-cables` | `bf9fabe` | **`a46d16a`** |
| Коммиты S-1 | `b88b965` (security), `bf9fabe` (renormalize), автор `backend-auditor (karier-improvements) <team@karier.local>` | **`45b8c21`**, **`57cbb71`**, автор `Sergey <dandjeydee@gmail.com>` (как у 55 из 57 коммитов истории) |
| Коммит гигиены индекса | — | **`a46d16a`** «chore(git): убрать .vs/ и .vercel/ из индекса и добавить их в .gitignore» (9 файлов, +4/−33) |
| `.vs/` и `.vercel/` в индексе | 8 файлов | **0** (на диске все 8 файлов на месте) |
| `.gitignore` | без правил для IDE/Vercel | +`.vs/`, +`.vercel/` (`.tmp/` и `.npm-cache/` уже были) |
| `C:\karier\.local\backups\rotation-20261124` | 3 файла со старым паролем | **удалён** (ротация подтверждена R1/V1) |
| `push` / remote | не было | **не было**; `origin` не менялся, upstream у ветки отсутствует |
| Цепочка коммитов | `efd3cd2 → b88b965 → bf9fabe` | `efd3cd2 → 45b8c21 → 57cbb71 → a46d16a` |

Дерево каждого переоформленного коммита **побайтово совпадает** с прежним (`git diff --stat` между
старым и новым HEAD — пусто), поэтому содержимое правок S-1 не изменилось: поменялись только
author/committer (и, как следствие, хеши).

---

## 2. Что сделано по шагам

### 2.1. Идентичность и авторство (R1-07)

- Владелец определён по истории: 55 из 57 коммитов оформлены как `Sergey <dandjeydee@gmail.com>`
  (остальные два — служебные S-1). Этот же аккаунт — автор `origin` (`github.com/Fonfond/karier-app`).
- В локальный конфиг репозитория записано:
  ```powershell
  git config user.name  'Sergey'
  git config user.email 'dandjeydee@gmail.com'
  ```
- Переоформлены два коммита S-1 — `b88b965` (security) и `bf9fabe` (renormalize).
  **Способ — plumbing `git commit-tree`, а не `git rebase`/`git commit --amend`:** в рабочем дереве
  лежат 44 незакоммиченные записи владельца, и интерактивный rebase/`--amend` потребовал бы чистого
  дерева или `git stash` (риск для чужой незавершённой работы). `commit-tree` создаёт новые коммиты
  с теми же деревьями и сообщениями, с новыми author/committer, и не трогает ни индекс, ни рабочее
  дерево:
  ```powershell
  $newMid  = git commit-tree <tree(mid)>  -p efd3cd2   # 45b8c21
  $newHead = git commit-tree <tree(head)> -p $newMid   # 57cbb71
  git update-ref -m 'S-1c: reset author of S-1 commits to owner' \
      refs/heads/feature/sprint-29-maintenance-cables $newHead bf9fabe
  ```
  Даты author/committer выставлены как у `--reset-author` (момент переоформления), сообщения
  коммитов сохранены дословно. Старые хеши остались только в reflog/pack (недостижимы из ветки).
- Другие 30 веток не затронуты (проверено `git branch --contains b88b965` — только текущая ветка,
  после переоформления — пусто).

### 2.2. Гигиена индекса (R1-01)

- Сняты из индекса каталоги IDE/Vercel (файлы на диске не тронуты):
  ```powershell
  git rm -r --cached --quiet .vs .vercel      # 8 записей: .vs/* — 6, .vercel/* — 2
  ```
- В `.gitignore` добавлен блок (UTF-8 без BOM, существующие строки не изменялись):
  ```gitignore
  # Служебные каталоги IDE/Vercel (S-1c: убраны из индекса)
  .vs/
  .vercel/
  ```
  `.tmp/` и `.npm-cache/` уже были в `.gitignore` («Рабочие каталоги и кэши стенда») — дублировать
  не стал.
- Отдельный коммит гигиены `a46d16a`: 9 файлов, `+4 −33` (`.gitignore` +4; 8 файлов удалены из
  индекса: `README.txt`, `project.json`, `ProjectSettings.json`, `VSWorkspaceState.json`,
  `DocumentLayout.json` и три бинарника — `.vsidx` 370 982 Б, `.wsuo` 12 800 Б, `slnx.sqlite` 90 112 Б).
  Первая попытка коммита содержала только удаления (`.gitignore` был не застейджен) — исправлено
  `git add .gitignore` + `git commit --amend --no-edit`; в итоговом `a46d16a` есть и правила, и удаления.

### 2.3. Бэкапы ротации (R1-02)

- Перед удалением проверено: путь резолвится ровно в `C:\karier\.local\backups\rotation-20261124`,
  он **вне** репозитория (`C:\karier\karier`), содержимое — 3 ожидаемых файла:
  `env.before-rotation.bak` (1 354 Б), `env.test.before-rotation.bak` (547 Б), `pg_hba.conf.after` (6 085 Б).
- Каталог удалён полностью (`Remove-Item -Recurse -Force`), `Test-Path` → `False`.
- Ротация к этому моменту подтверждена независимо: R1 (`docs/team/12-r1-review.md` §3.3: старый
  пароль — `psql` exit 2 / `FATAL`, новый — exit 0; `pg_hba` строки 120/121 `scram-sha-256`; хэш роли
  `SCRAM-SHA-256`) и V1 (`docs/team/11-v1-acceptance.md`). Поэтому бэкапы `.env` со старым паролем
  больше не нужны.
- Не тронуты: `C:\karier\.local\secrets\db-password.txt` (вне scope, ротация не откатывалась),
  остальные дампы в `C:\karier\.local\backups` (`karier_db_20261123…`, `karier_db_20261124…`,
  `karier_db_before_tests.dump`) — это дампы БД, а не бэкапы пароля.

---

## 3. Проверки

### 3.1. Команды приёмки (verify из контракта t28) — все exit 0

| # | Команда | Результат |
|---|---|---|
| 1 | `git ls-files -- .vs .vercel` + `exit 1` при непустом ответе | **`index-clean`**, exit 0 |
| 2 | `Select-String -Path .gitignore -Pattern '^\.vs/\|^\.vercel/'` → требуется ≥ 2 | **`ignore-rules-ok`**, 2 совпадения |
| 3 | `Test-Path C:\karier\.local\backups\rotation-20261124` | **`rotation-backups-removed`**, exit 0 |
| 4 | `git log -2 --format='%an <%ae> \| %s'` | три верхних коммита — `Sergey <dandjeydee@gmail.com>` (гигиена, renormalize, security) |

### 3.2. Дополнительные проверки

| Проверка | Результат |
|---|---|
| `git ls-files -- .vs .vercel` | 0 записей |
| Файлы на диске после `rm --cached` | все 8 на месте (`.vs` — 6 файлов, `.vercel` — 2) |
| `git status --porcelain \| Select-String '\.vs/\|\.vercel/'` | 0 — служебные каталоги больше не мешают статусу |
| `git status --porcelain` (всего) | 44 записи — это WIP владельца (`19 M + 18 ??` из S-1 плюс новые файлы волны), не тронуты |
| Деревья переоформленных коммитов | `git diff --stat bf9fabe 57cbb71` — пусто |
| Ветки, содержащие старые хеши | нет (`git branch --contains b88b965` / `bf9fabe` — пусто); 31 ветка на месте |
| Remote и upstream | `origin = https://github.com/Fonfond/karier-app.git` (не менялся), upstream отсутствует, `push` не выполнялся |
| `venv.broken*` | отсутствует (в `backend-v2` только `venv`, игнорируется) |
| Отслеживаемые `.pyc` / `__pycache__` | 0 |
| Остаточный старый пароль | 0 в отслеживаемом рабочем дереве; 0 в файлах `.local` (вне `secrets`/`backups`); остаётся только в untracked `backend\.env` (v1, вне scope) и в блобах истории git (R1-03) |
| `backend-v2\.env` / `backend-v2\tests\.env.test` | mtime 24.11 22:19:56 / 22:20:05 — не изменялись (новый пароль) |
| `C:\karier\.local\secrets\db-password.txt` | на месте, 32 Б, mtime 24.11 22:19:38 — не изменялся |

---

## 4. Что осталось владельцу

1. **Приватный remote и первый `push`** (не выполнялись): `origin` сейчас публичный
   `github.com/Fonfond/karier-app`; ветка `feature/sprint-29-maintenance-cables` — только локальная
   (upstream нет). Перед публикацией — `git remote add private …` и push в приватный репозиторий.
2. **Чистая история (R1-03) — главное:** переоформление авторства **не удаляет** старый пароль из
   блобов истории (коммиты `efd3cd2` и ранее; пароль введён `1463fe5`, удалён в `45b8c21`). Для
   публикации нужно либо `git filter-repo --replace-text`, либо новый репозиторий с «чистого»
   коммита; после перезаписи — `git gc --prune=now`, иначе старые объекты останутся в `.git`
   (сейчас они недостижимы из ветки, но лежат в pack/reflog). Команда этого не делала: нужна
   авторизация/решение владельца и это необратимая операция.
3. **`backend\.env` (легаси v1)** всё ещё содержит мёртвый старый пароль (untracked, в `.gitignore`,
   самый старый пароль отклоняется БД). Решение — в рамках I-40: удалить каталог v1 или обнулить
   его `.env`. Вне scope этой задачи файл не менялся (mtime 25.11 07:55 — не наша правка).
4. **Seed-пароли** `admin`/`operator123` (R1-04) — это I-06 следующей волны.
5. **`.local\secrets` ACL каталога** (R1-06) — принято как есть; при желании снять наследование и с
   каталога.
6. **Git в PATH** (из `08`): portable MinGit лежит в `C:\karier\tools\MinGit`, для постоянной работы
   добавить `C:\karier\tools\MinGit\cmd` в `PATH`.
7. **Пустой коммит `57cbb71`** («renormalize line endings») сохранён как есть — так решено капитаном
   (R1-05); при переписывании истории его можно объединить с `45b8c21`.

---

## 5. Замечания и ограничения

- `git status` теперь **не** содержит `.vs`/`.vercel`; сами каталоги остаются на диске (по контракту
  файлы не удалялись) и игнорируются — на будущие `git add -A` не влияют.
- При коммите `.gitignore` git предупреждал, что в рабочей копии CRLF будет заменён на LF — это
  косметика от `.gitattributes` (`* text=auto eol=lf`); в коммит попало 4 добавленные строки, ничего
  больше.
- Переоформление авторства — операция, меняющая историю ветки; она допустима только потому, что
  ветка **не опубликована** (проверено: у неё нет upstream, `origin/main = 5d930c5` — прототип).
  После push такие перезаписи потребуют force-push и согласования.
- Не выполнялись: `push`, создание remote, `filter-repo`, `gc`, изменение `backend-v2/**`,
  `src-v2/**`, `.local/secrets`, `.env`-файлов, перезапуск стека, запросы к `karier_db`.
- Отчёт лежит в `docs/team/` — каталог пока untracked (`?? docs/team/`), как и остальные отчёты
  команды; это не входит в коммит гигиены.

---

## 6. Приложение: команды (полный набор)

```powershell
$git = 'C:\karier\tools\MinGit\cmd\git.exe'; $r = 'C:\karier\karier'

# 1) идентичность владельца
& $git -C $r config user.name  'Sergey'
& $git -C $r config user.email 'dandjeydee@gmail.com'

# 2) переоформление двух коммитов S-1 (без rebase — дерево владельца грязное)
#    base = efd3cd2, mid = b88b965, head = bf9fabe; деревья/сообщения сохраняются
$newMid  = <msg(mid)>  | & $git -C $r commit-tree <tree(mid)>  -p efd3cd2        # 45b8c21
$newHead = <msg(head)> | & $git -C $r commit-tree <tree(head)> -p $newMid        # 57cbb71
& $git -C $r update-ref -m 'S-1c: reset author of S-1 commits to owner' `
    'refs/heads/feature/sprint-29-maintenance-cables' $newHead bf9fabe

# 3) индекс и .gitignore
& $git -C $r rm -r --cached --quiet .vs .vercel        # 8 записей, файлы на диске остаются
# .gitignore += блок с .vs/ и .vercel/
& $git -C $r add -- .gitignore
& $git -C $r commit -m "chore(git): убрать .vs/ и .vercel/ из индекса и добавить их в .gitignore"   # a46d16a

# 4) бэкапы ротации (вне репозитория) — после проверки пути
Remove-Item -LiteralPath 'C:\karier\.local\backups\rotation-20261124' -Recurse -Force

# 5) проверки
& $git -C $r ls-files -- .vs .vercel                    # пусто
Select-String -Path "$r\.gitignore" -Pattern '^\.vs/|^\.vercel/'   # 2 совпадения
Test-Path 'C:\karier\.local\backups\rotation-20261124'  # False
& $git -C $r log -4 --format='%h %an <%ae> | %s'        # a46d16a, 57cbb71, 45b8c21 — Sergey
& $git -C $r diff --stat bf9fabe 57cbb71                # пусто (деревья идентичны)
& $git -C $r status --porcelain                          # 44 записи WIP владельца, без .vs/.vercel
```
