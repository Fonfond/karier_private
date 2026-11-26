# 24 — F-1: Docker/Compose упаковка «Карьера»

**Дата:** 2026-11-26, 00:40–01:20 (локальное время машины, UTC+08:00)
**Кто:** `integrator` (задача t23, команда `karier-improvements`)
**Основание:** I-40/§4.2 плана и F-1: приложению нужна воспроизводимая поставка на собственный сервер
владельца (PostgreSQL + API + nginx), с конфигурацией только через `.env` и постоянными томами.
**Рамки:** добавлены только упаковочные файлы; код приложения, миграции, `src-v2/src` и `.env`
не менялись. `push`/коммитов нет.

## ВЕРДИКТ: постановка готова, **runtime-проверка заблокирована отсутствием Docker**

Docker на машине нет; установка Docker Desktop через `winget` требует прав администратора и
интерактивного подтверждения — в этой сессии недоступна (подробно §6). Поэтому выполнен
**статический контроль** поставки (81 проверка, 0 ошибок, §4) и подготовлена инструкция для машины
с Docker (§7). Файлы готовы к сборке; первая сборка и полный цикл `up/down` — на целевой машине.

---

## 1. Что собрано

| Файл | Назначение |
|---|---|
| `docker-compose.yml` | стек из трёх сервисов: `db` (postgres:18, том `pgdata`), `api` (сборка `backend-v2`, 1 воркер, тома `documents`/`media`), `web` (nginx со статикой, порт `${WEB_PORT:-8080}`); healthchecks у всех трёх, `api` ждёт `db` (service_healthy), `web` ждёт `api`; секретов в файле нет — всё из `.env` |
| `backend-v2/Dockerfile` | `python:3.14-slim`; `pip install -r requirements.txt` отдельным слоем; `ENTRYPOINT /app/entrypoint.sh`; `HEALTHCHECK` на `/api/health/ready` через python (без curl) |
| `backend-v2/entrypoint.sh` | ждёт PostgreSQL по `DATABASE_URL` (SQLAlchemy, таймаут 90 с), создаёт `var/documents`/`var/media`, делает `alembic upgrade head`, затем `exec uvicorn app.main:app --workers 1` |
| `backend-v2/.dockerignore` | исключает `.env*`, `venv*`, `__pycache__`, `var/`, `tests/`, `*.pyc`, `.coverage*`, `coverage.xml`, `*.map`, `.git` — контекст 116 файлов / **0,90 МБ** |
| `src-v2/Dockerfile` | multi-stage: `node:22-alpine` → `npm ci && npm run build`; рантайм `nginx:1.27-alpine`, `COPY dist`, удаление `*.map`, `HEALTHCHECK` через wget |
| `src-v2/.dockerignore` | `node_modules/`, `dist/`, `.env*`, `*.map`, `.git` — контекст 97 файлов / **1,92 МБ** |
| `deploy/nginx.conf` | SPA-fallback, `/api/` → `http://api:8000`, `.map` → 404, статика `immutable` 30 дней, `index.html`/`sw.js` без кэша, `client_max_body_size 25m`, security-заголовки, gzip; монтируется в `/etc/nginx/conf.d/default.conf` (ro) |
| `.env.example` (корень) | конфигурация стека: `POSTGRES_*`, `WEB_PORT`, `ENV=prod`, `SECRET_KEY=__ЗАМЕНИТЕ…__`, `COOKIE_SECURE=true`, лимиты, каталоги файлов, `TRUSTED_PROXIES`; реальных значений нет |

Хеши (SHA-256):

```
docker-compose.yml          39D5803D6FEF6053C820926FF03F167B39BC3F87D7233BAC3B7D3FF730A8A7D5
.env.example                35DB3B14D8225442DE9EEBBDB2B41C0A94E53FFFD3B0E6D769150F705BFAE9AD
backend-v2/Dockerfile       3EB7F0FB796CB63DB0AB79230CABF9B37D585EEBCA836EBE5D6D38CB69CF6FDD
backend-v2/entrypoint.sh    42FE7278F421D81E9604B9C2044185FCD23E9F51995968BF4C652774146D9541
backend-v2/.dockerignore    07518BFFB98EF7C01F61F830DD74CFFE5011FA45AF164A8678AC3793F0AA9844
src-v2/Dockerfile           B75F1BCE5048D1DB91906673C0514BA9DC4C5C9820E58E548669977755A3FB48
src-v2/.dockerignore        77162CCE5801964C43B6A186772882614ABA20B7D235D57EE9F7E07E3F4CA23C
deploy/nginx.conf           ED69F7D33854FE5F9C843701C06F0F3BDE30B3B2704B1257C99359C59EE3E26D
```

---

## 2. Как устроен жизненный цикл

1. `docker compose up -d --build` → `db` стартует, healthcheck `pg_isready` становится healthy.
2. `api` ждёт `db` (compose condition), затем entrypoint: ожидание БД по `DATABASE_URL` →
   `alembic upgrade head` (14 миграций, head `0014_schema_snapshots`) → `uvicorn` с **одним воркером**
   (у rate-limit и части состояния — память процесса, поэтому `API_WORKERS=1` по умолчанию).
3. `web` ждёт `api` healthy, nginx отдаёт `index.html`/ассеты и проксирует `/api/` на `api:8000`.
4. `docker compose down` (без `-v`) сохраняет `pgdata`, `documents`, `media`; `down -v` удаляет их —
   это осознанный способ «сбросить стенд начисто».

---

## 3. Тома и данные

| Том | Куда | Что хранится |
|---|---|---|
| `pgdata` | `/var/lib/postgresql/data` | база `karier_db` |
| `documents` | `/app/var/documents` | документы объектов (`DOCUMENTS_DIR`) |
| `media` | `/app/var/media` | фото и медиа (`MEDIA_DIR`) |

Тома именованные, поэтому переживают `down`/`up`, пересборку образов и обновление кода. Удалить —
`docker compose down -v` (или `docker volume rm karier_documents` и т.п.).

---

## 4. Статическая проверка (Docker недоступен)

Скрипт `C:\karier\.local\f1-static-check.py` (вне репозитория) проверил **81 утверждение — 0 ошибок**:

* **compose:** YAML валиден; ровно сервисы `db/api/web`; `postgres:18`; healthchecks у всех;
  `api` → `db` и `web` → `api` через `service_healthy`; объявлены и примонтированы тома
  `pgdata`/`documents`/`media`; `WEB_PORT` публикуется, `db`/`api` — нет; build-контексты существуют;
  тегов `latest` нет; все `${VAR}` из compose описаны в `.env.example`; секретов нет.
* **Dockerfile api:** `python:3.14-slim`, `ENTRYPOINT /app/entrypoint.sh`, `chmod +x`, `HEALTHCHECK`,
  нет `COPY .env`, нет `latest`.
* **Dockerfile web:** `node:22-alpine` → `nginx:1.27-alpine`, `COPY --from=build /app/dist`,
  удаление `*.map`, `HEALTHCHECK`.
* **entrypoint.sh:** `#!/bin/sh`, `set -eu`, обязательный `DATABASE_URL`, ожидание БД (`select 1`),
  `alembic upgrade head`, `exec uvicorn app.main:app`, `API_WORKERS=1`, LF-переводы строк, нет секретов.
* **nginx.conf:** баланс скобок, SPA-fallback, `/api/` → `api:8000`, `.map` → 404, `immutable`-кэш,
  `no-store` для `index.html`/`sw.js`, `client_max_body_size`, security-заголовки, gzip.
* **.dockerignore:** симуляция контекста — `.env`, `.env.test`, `venv/`, `node_modules/`, `dist/`,
  `var/`, `__pycache__`, `*.map`, `.coverage*` **исключены**; контексты 116 файлов / 0,90 МБ
  (api) и 97 файлов / 1,92 МБ (web).
* **секреты:** ни старый, ни новый пароль БД не встречаются ни в `.env.example`, ни в compose,
  ни в файлах, попадающих в контексты сборки.

Ветки verify без Docker выполнены и дали ожидаемое:
`static-check-only` (файлы на месте, exit 0) и `skip-runtime-no-docker` (exit 0).

---

## 5. Что проверено / что осталось проверить

| Критерий | Статус |
|---|---|
| compose описывает api (1 воркер), postgres, web/nginx; api ждёт БД, применяет миграции | **статически подтверждено** (healthcheck/entrypoint/condition); запуск — на машине с Docker |
| web раздаёт фронтенд без sourcemap и проксирует /api | **статически**: nginx.conf + удаление `*.map` в образе; сборка `vite` без sourcemap (S-7) |
| Персистентные тома pgdata/documents/media | **статически**: тома объявлены и примонтированы |
| Healthcheck `/api/health/ready`, контейнеры healthy | **статически**: HEALTHCHECK в обои́х образах + compose healthchecks |
| Секретов в образах/репозитории нет | **проверено**: `.env` не в контексте, `.env.example` — заглушки, скан обоих контекстов чист |
| Сборка воспроизводима с нуля | зависит от сети/базы образов; проверить `up --build` на целевой машине |
| Полный цикл: up → вход 000001 → карта/схема → down -v → up | **не выполнен: нет Docker** (блокер §6) |

---

## 6. Блокер: почему runtime-цикл не выполнен

Проверено на этой машине (2026-11-26, 00:40–01:00):

| Проверка | Результат |
|---|---|
| `Get-Command docker` | не найден; `C:\Program Files\Docker\Docker\Docker Desktop.exe` отсутствует |
| `winget --version` | 1.29.380 (есть), установщик Docker Desktop — `desktop.docker.com/win/main/amd64/…/Docker Desktop Installer.exe` |
| Права сессии | **не администратор** (`IsInRole(Administrator) = False`); approval-подсказки в сессии отключены |
| `winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements --disable-interactivity` | **не завершилась за 150 с** (загрузка установщика/ожидание повышения прав), процесс остановлен; `docker` по-прежнему отсутствует, каталога Docker нет |
| WSL | `wsl.exe` есть, дистрибутивов не выявлено (вывод — только баннер), Docker в WSL не установлен |

**Вывод:** установка Docker Desktop требует прав администратора и интерактивного UAC — в этой сессии
невозможна. Это инфраструктурный блокер, а не дефект поставки; все файлы проверены статически, а
проверка цикла вынесена на машину с Docker (§7). Пробовать другие способы (WSL+rootless docker,
Podman) в рамках этой задачи не стал: это меняет требования владельца к среде и требует его решения.

---

## 7. Инструкция для машины с Docker (полный цикл)

```bash
# 0) на сервере: Docker Engine + compose plugin (или Docker Desktop)
docker --version && docker compose version

# 1) конфигурация: реальный .env рядом с compose, без коммита
cp .env.example .env
#    отредактировать: POSTGRES_PASSWORD, SECRET_KEY (32+ символов), PUBLIC_BASE_URL,
#    CORS_ORIGINS, COOKIE_SECURE=true при HTTPS

# 2) сборка и запуск с нуля
docker compose up -d --build
docker compose ps                 # ожидаем: db/api/web — healthy
docker compose logs -f api        # в логе: «ждём PostgreSQL» → «alembic upgrade head» → «uvicorn»

# 3) проверки
curl -fsS http://127.0.0.1:8080/api/health/ready      # {"status":"ok","database":"ok"}
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/            # 200 (SPA)
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/sw.js       # 200
#   вход: POST /api/auth/login {"tab_no":"000001","password":"admin"} → 200
#   UI: открыть http://<host>:8080, войти, проверить карту и схему
#   ассеты: curl -I http://127.0.0.1:8080/assets/<файл>.js → Cache-Control: immutable
#   sourcemap: curl -I http://127.0.0.1:8080/assets/<файл>.js.map → 404

# 4) персистентность и повторный запуск
docker compose exec db psql -U karier_user -d karier_db -c 'select count(*) from gis.assets'
docker compose down               # без -v: тома сохраняются
docker compose up -d              # данные на месте, миграции повторно идемпотентны
docker compose down -v            # полный сброс (БД, документы, медиа)
docker compose up -d --build      # «с нуля»: миграции создадут схему, вход 000001 после seed — см. ниже
```

Замечание про первый вход: миграции создают **схему**, но не пользователей — учётка `000001` и демо-данные
появляются из seed-скриптов (`backend-v2/seed*.py`). Для «чистого» сервера нужно однократно выполнить
`docker compose exec api python seed.py` (и при необходимости `seed_gis.py`/`seed_break_glass.py`) либо
восстановить дамп; это описано в `docs/54-deploy-guide.md`. Пароль `000001` после seed — стендовый
(`admin`), его нужно сменить (I-06).

---

## 8. Ограничения и риски

1. **Образы не собирались** (нет Docker): синтаксис Dockerfile проверен статически, но первый
   `build` может выявить нюансы (сеть/теги базовых образов/слои). Рекомендация: первый запуск — на
   целевой машине, лог сборки приложить к приёмке.
2. **nginx.conf монтируется**, а не запекается в образ (так файл живёт в репозитории и в
   `deploy/`, а контекст web остаётся маленьким). Если запускать образ без compose — конфиг нужно
   передать вручную: `docker run -v $PWD/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro …`.
3. **`COOKIE_SECURE=true` требует HTTPS.** В compose сайт слушает `:8080` по HTTP; при выкладке за
   TLS-прокси (или с сертификатом в nginx) это заработает, для локального теста по HTTP нужно
   временно `COOKIE_SECURE=false` (описано в `.env.example`).
4. **`API_WORKERS=1` — осознанно**: rate-limit и часть кэшей в памяти процесса; при переходе на
   несколько воркеров нужен общий стор (I-41).
5. **`TRUSTED_PROXIES`**: запросы к api приходят от nginx (другая машина/контейнер), поэтому XFF
   учитывается только если адрес прокси указан в переменной; иначе в аудит/лимиты пойдёт IP nginx.
6. **Seed-данные не входят в образ** (`tests/`, `var/`, дампы исключены `.dockerignore`) — наполнение
   стенда отдельным шагом (§7).
7. **`docs/55-deploy-docker.md` и `docs/56-field-guide.md`** не создавались (out of scope задачи).

---

## 9. Откат

Упаковка аддитивна: удалить `docker-compose.yml`, `.env.example`, `backend-v2/Dockerfile`,
`backend-v2/entrypoint.sh`, `backend-v2/.dockerignore`, `src-v2/Dockerfile`, `src-v2/.dockerignore`,
`deploy/nginx.conf` — приложение и текущий стенд не затронуты. Контейнеры/тома, если появятся:
`docker compose down -v`.
