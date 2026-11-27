# 55 — Развёртывание «Карьера» через Docker на собственном сервере

Пошаговая инструкция для администратора: от чистой Ubuntu до рабочего стенда с картой и схемой.
Поставка подготовлена в F-1 (`docker-compose.yml`, `backend-v2/Dockerfile`, `src-v2/Dockerfile`,
`deploy/nginx.conf`, `.env.example`). Здесь — как этим пользоваться; секретов в документе нет,
все значения вы задаёте сами и храните только в `.env` на сервере.

**Оглавление**

1. [Что получится](#1-что-получится)
2. [Требования к серверу](#2-требования-к-серверу)
3. [Установка Docker](#3-установка-docker)
4. [Код на сервере](#4-код-на-сервере)
5. [Конфигурация `.env`](#5-конфигурация-env)
6. [Сборка и запуск](#6-сборка-и-запуск)
7. [Первичная инициализация: учётки, seed, OTP](#7-первичная-инициализация-учётки-seed-otp)
8. [Проверка работоспособности](#8-проверка-работоспособности)
9. [Второй карьер и фидеры от ПС 35-6](#9-второй-карьер-и-фидеры-от-пс-35-6)
10. [Бэкап и восстановление](#10-бэкап-и-восстановление)
11. [Обновление версии и откат](#11-обновление-версии-и-откат)
12. [Логи и диагностика](#12-логи-и-диагностика)
13. [TLS и внешний прокси](#13-tls-и-внешний-прокси)
14. [Чек-лист приёмки](#14-чек-лист-приёмки)
15. [Ограничения](#15-ограничения)

---

## 1. Что получится

```
                 ┌───────────────────────────── сервер ─────────────────────────────┐
  браузер ──► :8080 ─► web (nginx)  ── /api/ ──► api (uvicorn, 1 воркер) ──► db (PostgreSQL 18)
                       статика SPA                entrypoint: ждёт БД,                том pgdata
                       без .map                    alembic upgrade head                 документы/медиа:
                                                                                       тома documents/media
```

* **api** — FastAPI `app.main:app`, один воркер (`API_WORKERS=1`): rate-limit и часть состояния живут
  в памяти процесса.
* **web** — nginx: раздаёт собранный SPA, проксирует `/api/`, `.map` отдаёт 404, статику кэширует.
* **db** — PostgreSQL 18, наружу не публикуется.
* Данные: `pgdata` (БД), `documents` (`var/documents`), `media` (`var/media`) — именованные тома,
  переживают `down`/`up` и обновления.
  > **PostgreSQL 18+**: том `pgdata` монтируется в `/var/lib/postgresql` (данные — в подкаталоге
  > `<major>/docker`), а не в `/var/lib/postgresql/data`. Старый путь на образе 18 приводит к
  > `Restarting` БД и ошибке «there appears to be PostgreSQL data in /var/lib/postgresql/data».

---

## 2. Требования к серверу

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| ОС | Linux amd64 (Ubuntu 22.04/24.04, Debian 12) | Ubuntu 24.04 LTS |
| CPU / RAM | 2 vCPU / 2 ГБ | 2–4 vCPU / 4 ГБ |
| Диск | 20 ГБ SSD | 40+ ГБ (дают запас под дампы и фото) |
| Docker | Engine 24+, compose plugin v2 | актуальный из официального репозитория |
| Сеть | исходящий HTTPS (сборка образов), входящий 8080 (или 80/443 за TLS-прокси) | DNS-имя + TLS-сертификат |

Дополнительно для работы людей в поле: доступ по локальной сети и телефон/планшет (PWA), но это
не требование к серверу.

---

## 3. Установка Docker

```bash
# 1) базовые пакеты
sudo apt update
sudo apt install -y ca-certificates curl gnupg

# 2) официальный репозиторий Docker (Ubuntu/Debian)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3) проверка
docker --version
docker compose version
sudo docker run --rm hello-world
```

Чтобы работать без `sudo`:

```bash
sudo usermod -aG docker "$USER"   # затем перелогиниться
```

> Для локальной проверки на Windows/macOS подойдёт Docker Desktop (нужны права администратора и
> WSL2/виртуализация). На бою — Linux.

---

## 4. Код на сервере

```bash
sudo mkdir -p /opt/karier && sudo chown "$USER":"$USER" /opt/karier
cd /opt/karier
git clone <адрес-репозитория> .      # либо rsync/архив релиза
git checkout <нужный тег/ветка>
```

Что должно быть в каталоге и что **не** нужно копировать:

```
/opt/karier
├── docker-compose.yml          ← стек
├── .env                        ← ВАШИ секреты (создаётся из .env.example, в git не попадает)
├── .env.example                ← шаблон без значений
├── backend-v2/                 ← api: Dockerfile, entrypoint.sh, app/, alembic/, seed*.py
├── src-v2/                     ← web: Dockerfile, package.json, src/, public/
├── deploy/nginx.conf           ← конфиг nginx (монтируется в контейнер)
└── docs/                       ← документация
```

НЕ копируйте и не создавайте на сервере: `backend-v2/venv*`, `backend-v2/.env`,
`src-v2/node_modules`, `src-v2/dist`, `backups/` (372 МБ дампов), `.git` при передаче архивом —
это исключено `.dockerignore` и не нужно для сборки.

---

## 5. Конфигурация `.env`

```bash
cd /opt/karier
cp .env.example .env
chmod 600 .env
# сгенерировать секреты (вставьте результат в .env)
openssl rand -base64 48            # SECRET_KEY (≥32 символов)
openssl rand -base64 32            # POSTGRES_PASSWORD
```

### 5.1. Все переменные

| Переменная | Обязательна | Значение / пояснение |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | да (есть дефолт) | роль и база внутри контейнера `db`; менять после первого запуска нельзя без восстановления |
| `POSTGRES_PASSWORD` | **да** | пароль роли БД; генерируется, хранится только в `.env` |
| `WEB_PORT` | нет (8080) | внешний порт сайта на хосте; за TLS-прокси можно не публиковать |
| `ENV` | да | `prod` на сервере (включает проверку секретов и запрет `EXPOSE_OTP_CODE=true`) |
| `SECRET_KEY` | **да** | подпись токенов, ≥32 случайных символов; смена разлогинит всех |
| `DEBUG` | нет | `false` в prod (не отдавать трейсбеки) |
| `DATABASE_URL` | формирует compose | **не задавайте вручную**: compose собирает `postgresql+psycopg://…@db:5432/…` из `POSTGRES_*`; значение из `.env` перекрывается |
| `API_WORKERS` | нет (1) | оставьте `1`: rate-limit в памяти процесса (для нескольких воркеров нужен общий стор) |
| `COOKIE_SECURE` | да | `true` при HTTPS (TLS-прокси), `false` только для локального HTTP-теста |
| `COOKIE_SAMESITE` | нет (lax) | оставьте `lax`; `none` — только при необходимости кросс-доменных cookie (требует `Secure`) |
| `CORS_ORIGINS` | да при внешнем фронте | список origin через запятую, например `https://karier.example.ru`; пусто — только same-origin |
| `PUBLIC_BASE_URL` | да | публичный адрес сайта `https://karier.example.ru` — используется в QR паспорта и ссылках документов |
| `EXPOSE_OTP_CODE` | нет | **`false`**: коды OTP выдаёт администратор вручную (в prod `true` запрещён) |
| `CONSOLE_NOTIFICATIONS` | нет | `false`: не печатать уведомления/коды в лог |
| `ACCESS_TOKEN_TTL_MIN` | нет (15) | время жизни access-токена, минуты |
| `REFRESH_TOKEN_TTL_DAYS` | нет (30) | время жизни refresh-cookie, дни |
| `RATE_LIMIT_LOGIN_PER_MINUTE`, `RATE_LIMIT_REGISTER_PER_HOUR` | нет | лимиты попыток входа/регистрации |
| `TRUSTED_PROXIES` | да при внешнем прокси | IP/CIDR прокси, которым доверяем `X-Forwarded-For` (через запятую); иначе в аудите будет IP nginx |
| `DOCUMENTS_DIR` | нет (`var/documents`) | каталог документов внутри контейнера (том `documents`) |
| `MEDIA_DIR` | нет (`var/media`) | каталог медиа внутри контейнера (том `media`) |
| `STORAGE_BACKEND` | да | `local` для собственного сервера (файлы в томах); `vercel_blob` — только для Vercel |
| `MAX_DOCUMENT_MB`, `MAX_PHOTO_MB` | нет | лимиты размеров; согласованы с `client_max_body_size 25m` в nginx |
| `DOCUMENT_URL_TTL_MIN`, `MEDIA_URL_TTL_MIN`, `EXPORT_URL_TTL_MIN` | нет | время жизни подписанных ссылок/экспорта |
| `PDF_FONT_PATH` | нет | TTF с кириллицей для PDF; пусто — поиск в системе |

### 5.2. Пример `.env` (значения — заглушки, замените!)

```dotenv
POSTGRES_USER=karier_user
POSTGRES_PASSWORD=__ВСТАВЬТЕ_СГЕНЕРИРОВАННЫЙ_ПАРОЛЬ__
POSTGRES_DB=karier_db
WEB_PORT=8080

ENV=prod
DEBUG=false
SECRET_KEY=__ВСТАВЬТЕ_СЛУЧАЙНУЮ_СТРОКУ_32+_СИМВОЛОВ__
API_WORKERS=1

COOKIE_SECURE=true
COOKIE_SAMESITE=lax
ACCESS_TOKEN_TTL_MIN=15
REFRESH_TOKEN_TTL_DAYS=30

CORS_ORIGINS=https://karier.example.ru
PUBLIC_BASE_URL=https://karier.example.ru
TRUSTED_PROXIES=172.18.0.1

EXPOSE_OTP_CODE=false
CONSOLE_NOTIFICATIONS=false
RATE_LIMIT_LOGIN_PER_MINUTE=10
RATE_LIMIT_REGISTER_PER_HOUR=20

DOCUMENTS_DIR=var/documents
MEDIA_DIR=var/media
STORAGE_BACKEND=local
MAX_DOCUMENT_MB=25
MAX_PHOTO_MB=15
```

Проверка, что в `.env` нет случайных значений из шаблона:

```bash
grep -n '__' .env && echo "ОСТАНОВИТЕСЬ: замените заглушки" || echo ".env заполнен"
```

> Внутри сети compose БД доступна по имени `db`; наружу порт 5432 не публикуется — это нормально.

---

## 6. Сборка и запуск

```bash
cd /opt/karier
docker compose config -q          # синтаксис и подстановка переменных
docker compose build              # api и web (первый раз 3–8 минут)
docker compose up -d
docker compose ps                 # ждём healthy у db, api, web (1–2 минуты на первый старт)
```

Что происходит автоматически:

1. `db` поднимается, healthcheck `pg_isready` становится `healthy`;
2. `api` стартует только после этого; entrypoint ждёт БД (до 90 с), выполняет
   **`alembic upgrade head`** (14 миграций, head `0014_schema_snapshots`), затем запускает uvicorn;
3. `web` стартует после `api healthy`.

```bash
docker compose logs -f api        # «ждём PostgreSQL» → «alembic upgrade head» → «uvicorn 0.0.0.0:8000»
```

Миграции отдельно (если нужно вручную):

```bash
docker compose exec api alembic current      # должно быть 0014 (head)
docker compose exec api alembic heads
docker compose exec api alembic upgrade head # идемпотентно
```

---

## 7. Первичная инициализация: учётки, seed, OTP

Миграции создают **схему**, но не пользователей и не демо-данные. На чистой базе выполните один раз
(порядок важен):

```bash
cd /opt/karier
docker compose exec api python seed.py               # роли/права + 000001, 000002, 000003
docker compose exec api python seed_gis.py           # карьер, подложка, типы, объекты
docker compose exec api python seed_topology.py      # секции, ячейки, линии (фидеры), связи
docker compose exec api python seed_schema_blocks.py # библиотека блоков
docker compose exec api python seed_demo.py          # демо: фото, дефекты, обход (необязательно)
docker compose exec api python seed_break_glass.py   # аварийная учётка 000000 — ТОЛЬКО вывод в консоль
```

Правила для учёток:

| Что | Как | Что сделать сразу |
|---|---|---|
| `000001` (администратор) | `seed.py`, временный пароль печатается в консоль | войти и сменить пароль в «Профиле» |
| `000002` (оператор) | `seed.py`; TOTP-секрет и QR печатаются | завести в аутентификаторе или сменить |
| `000003` (регистровый демо) | `seed.py` | удалить/заблокировать на бою |
| `000000` (break-glass) | `seed_break_glass.py` печатает пароль, TOTP-секрет и QR **один раз** | распечатать, запечатать, в сейф; в системе не хранится |
| Остальные сотрудники | админка «Сотрудники» → «Завести» | пароль задаёт сам сотрудник после кода |

**Ручная выдача OTP (регистрация/сброс).** При `EXPOSE_OTP_CODE=false` код не уходит в ответе и в лог.
Администратор открывает «Сотрудники» → у сотрудника без пароля «Выдать код» и передаёт код лично
(код показывается один раз, живёт 10 минут). Через API то же самое:

```bash
# токен администратора: см. §8 (login)
curl -sS -X POST "http://127.0.0.1:8080/api/employees/<employee_id>/otp" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" | head -c 400
```

Повторная выдача отменяет предыдущий код (`400` на старый). `resend_invite` код не возвращает.
Ротация аварийного доступа: `docker compose exec api python reset_break_glass.py`
(и `--disable`, чтобы заблокировать учётку).

---

## 8. Проверка работоспособности

```bash
# 8.1. Базовая доступность (через web-контейнер, порт WEB_PORT)
curl -fsS http://127.0.0.1:8080/api/health/ready ; echo
#   ожидается: {"status":"ok","service":"karier-api","version":"0.1.0","database":"ok"}
curl -fsS -o /dev/null -w 'index=%{http_code}\n' http://127.0.0.1:8080/
curl -fsS -o /dev/null -w 'sw=%{http_code}\n'    http://127.0.0.1:8080/sw.js

# 8.2. Статика кэшируется, sourcemap недоступен
ASSET=$(curl -sS http://127.0.0.1:8080/ | grep -o '/assets/index-[^"]*\.js' | head -1)
curl -sSI "http://127.0.0.1:8080$ASSET" | grep -i cache-control      # immutable
curl -sS -o /dev/null -w 'map=%{http_code}\n' "http://127.0.0.1:8080$ASSET.map"   # 404

# 8.3. Вход (получите токен; пароль — тот, что задали/сменили в §7)
TOKEN=$(curl -sS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tab_no":"000001","password":"__ПАРОЛЬ_АДМИНИСТРАТОРА__"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "${TOKEN:0:12}…"

# 8.4. Данные и схема
curl -sS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8080/api/assets?limit=2" | head -c 300; echo
curl -sS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8080/api/topology/graph" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("nodes",len(d["nodes"]),"edges",len(d["edges"]))'
```

UI-проверка в браузере: `http://<сервер>:8080` → вход → «Карта» (объекты на подложке, связи,
переключение питания) → «Схема» (граф, узлы/связи, легенда) → «Реестр» (поиск, карточка).
Ожидаемо: health `ok`, вход 200, карта и схема отрисовываются.

---

## 9. Второй карьер и фидеры от ПС 35-6

**Модель.** Второй карьер питается от той же **ПС 35-6**, но по другой отходящей линии. Фидер — это
строка `gis.lines` (`code` вида `ф.21К`, `ф.7К`, `ВЛ-6кВ-4`), а принадлежность участка сети к фидеру —
`gis.links.line_id`. Принадлежность объекта считается обходом «вниз по потоку» от головного участка
линии; границей служит связь, помеченная другой линией; связи без `line_id` — продолжение текущего
фидера. Объект может быть в нескольких фидерах (у БКРУ-1 основное и резервное питание) — это нормально.

**Что реализовано (S-8, backend).** `GET /api/assets` и `GET /api/topology/graph` принимают
`?line_id=<uuid>` или `?feeder=<код>`; в объектах/узлах есть `feeders[]`, в корне ответа — `feeder`.
Неизвестный фидер → `200` и пустой список (`feeder: null`). Часть `app/services/topology.py`:
`feeder_view`, `feeder_asset_ids`, `resolve_feeder`.

**Как проверить разделение на развёрнутом стенде:**

```bash
# 1) какие фидеры есть (справочник линий)
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/lines \
  | python3 -c 'import sys,json;[print(l["code"],"|",l["name"],"| links:",l["links_count"]) for l in json.load(sys.stdin)]'
#   в демо-данных: ф.21К, ф.7К, ВЛ-6кВ-4

# 2) реестр по фидеру второго карьера (ВЛ-6кВ-4) — обходы/опоры/КТП только этого фидера
curl -sS -G -H "Authorization: Bearer $TOKEN" --data-urlencode 'feeder=ВЛ-6кВ-4' \
  --data 'limit=500' http://127.0.0.1:8080/api/assets \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("total",d["total"]);[print(i["code"],i["name"],[f["code"] for f in i["feeders"]]) for i in d["items"][:10]]'

# 3) тот же фильтр по id линии (эквивалентно)
LINE_ID=$(curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/lines \
  | python3 -c 'import sys,json;print(next(l["id"] for l in json.load(sys.stdin) if l["code"]=="ВЛ-6кВ-4"))')
curl -sS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8080/api/assets?line_id=$LINE_ID&limit=5" | head -c 300

# 4) граф схемы по фидеру: только узлы этого фидера, связи — если оба конца в нём
curl -sS -G -H "Authorization: Bearer $TOKEN" --data-urlencode 'feeder=ф.21К' \
  http://127.0.0.1:8080/api/topology/graph \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("nodes",len(d["nodes"]),"edges",len(d["edges"]),"feeder",d["feeder"]["code"] if d["feeder"] else None)'

# 5) негативная проверка: неизвестный фидер — пусто, без ошибки
curl -sS -G -H "Authorization: Bearer $TOKEN" --data-urlencode 'feeder=НЕТ-ТАКОГО' \
  http://127.0.0.1:8080/api/assets | head -c 200     # {"items":[],"total":0,"feeder":null}
```

**Что должно получиться (демо-данные):** `ф.21К` → `KTP-14` и объекты основного питания, **без** `POLE-3`;
`ВЛ-6кВ-4` → `POLE-1…POLE-3` второго карьера; `BKRU-1` присутствует в обоих фидерах (`ф.21К` и `ф.7К`).
В карточке/списке у объекта видно `feeders[]` — по нему и проверяется привязка.

**Проверка «на глаз» в UI:** откройте «Схему» и «Реестр» — объекты обоих фидеров видны вместе (это
ожидаемо: фильтр по фидеру в интерфейсе пока не выведен, S-8 сделан на уровне API). Разделение
проверяется запросами выше и полем `feeders`; отсутствие пересечений, кроме двойного питания БКРУ-1,
подтверждает корректность.

**Если объекты «смешались»:** проверьте, что у головных связей второго фидера заполнен `line_id`:

```bash
docker compose exec db psql -U karier_user -d karier_db -c \
  "select l.code, count(*) from gis.links k join gis.lines l on l.id=k.line_id
     where k.deleted_at is null group by l.code order by l.code;"
```

Объекты без выхода на линию (новые контуры, «свежие» объекты) в фильтр не попадают — это норма, они
доступны по карточке. Подробная семантика — `docs/team/15-s8-feeders.md`.

---

## 10. Бэкап и восстановление

### 10.1. Бэкап БД (ежедневно в cron)

```bash
sudo mkdir -p /opt/karier-backups && sudo chown "$USER":"$USER" /opt/karier-backups

cat > /opt/karier-backup.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/karier
STAMP=$(date +%F_%H%M)
OUT=/opt/karier-backups/karier_db-$STAMP.dump
docker compose exec -T db pg_dump -U karier_user -d karier_db -Fc > "$OUT"
docker compose exec -T db pg_dump -U karier_user -d karier_db -s > /opt/karier-backups/schema-$STAMP.sql
find /opt/karier-backups -name 'karier_db-*.dump' -mtime +30 -delete
echo "backup: $OUT ($(du -h "$OUT" | cut -f1))"
SH
chmod +x /opt/karier-backup.sh

# cron: каждый день в 02:30
( crontab -l 2>/dev/null; echo "30 2 * * * /opt/karier-backup.sh >> /var/log/karier-backup.log 2>&1" ) | crontab -
/opt/karier-backup.sh        # проверить немедленно
```

### 10.2. Бэкап томов (документы и медиа)

```bash
cd /opt/karier
STAMP=$(date +%F)
docker run --rm -v karier_documents:/data -v /opt/karier-backups:/backup alpine \
  tar czf "/backup/documents-$STAMP.tgz" -C /data .
docker run --rm -v karier_media:/data -v /opt/karier-backups:/backup alpine \
  tar czf "/backup/media-$STAMP.tgz" -C /data .
ls -lh /opt/karier-backups
```

> Файлы БД — не единственное, что нужно: без томов документы/фото останутся «битыми ссылками».
> Дампы и архивы храните **вне** каталога проекта и, желательно, на другом носителе.

### 10.3. Восстановление

```bash
cd /opt/karier

# 1) остановить api (web можно оставить — он будет отдавать 502 на /api)
docker compose stop api

# 2) восстановить БД: удобнее в новую базу, затем переименовать
docker compose exec -T db psql -U karier_user -d karier_db -c \
  "drop database if exists karier_restore;" 
docker compose exec -T db psql -U karier_user -d karier_db -c \
  "create database karier_restore owner karier_user;"
docker compose exec -T db pg_restore -U karier_user -d karier_restore --no-owner --clean --if-exists \
  < /opt/karier-backups/karier_db-<ДАТА>.dump

# 3) если база «родная» и пустая — можно сразу в неё:
#    docker compose exec -T db pg_restore -U karier_user -d karier_db --no-owner --clean --if-exists < dump

# 4) восстановить тома
docker run --rm -v karier_documents:/data -v /opt/karier-backups:/backup alpine \
  sh -c 'rm -rf /data/* && tar xzf /backup/documents-<ДАТА>.tgz -C /data'
docker run --rm -v karier_media:/data -v /opt/karier-backups:/backup alpine \
  sh -c 'rm -rf /data/* && tar xzf /backup/media-<ДАТА>.tgz -C /data'

# 5) поднять и проверить
docker compose up -d
curl -fsS http://127.0.0.1:8080/api/health/ready; echo
docker compose exec api alembic current
```

После восстановления проверьте: вход, карту, схему, наличие фото/документов у 2–3 объектов,
`change_log` доступен на чтение (аудит append-only, восстановление допустимо только из дампа).

---

## 11. Обновление версии и откат

### 11.1. Обновление

```bash
cd /opt/karier
/opt/karier-backup.sh                     # 1) бэкап БД (тома — по расписанию/при изменении файлов)
git fetch --all --tags && git checkout <новый-тег>
docker compose build                      # 2) новые образы
docker compose up -d                      # 3) пересоздаст api/web; entrypoint применит миграции
docker compose ps                         # ждём healthy
curl -fsS http://127.0.0.1:8080/api/health/ready; echo
docker compose logs --tail=100 api        # убедиться, что миграции прошли без ошибок
```

Правила: обновляйтесь **после** бэкапа; тяжёлые/необратимые миграции (`DROP`, `ALTER TYPE`) —
только по инструкции релиза; фронтенд и бэкенд обновляйте вместе (контракт API может меняться
аддитивно).

### 11.2. Откат

```bash
cd /opt/karier
git checkout <предыдущий-тег>
docker compose build
docker compose up -d
```

Если новая версия уже изменила данные несовместимо — откат кода не поможет: восстановите дамп из §10.3
(это единственный гарантированный путь). `alembic downgrade -1` допустим только для отката последней
аддитивной миграции и только после бэкапа:

```bash
docker compose exec api alembic current
docker compose exec api alembic downgrade -1     # осторожно: проверьте, что миграция обратима
```

Зафиксируйте версию образов, если нужно быстрое возвращение:

```bash
docker tag karier-api:latest karier-api:2026-11-25
docker tag karier-web:latest karier-web:2026-11-25
```

---

## 12. Логи и диагностика

```bash
docker compose ps                              # состояние и health
docker compose logs -f api                     # логи приложения (uvicorn/аудит)
docker compose logs -f web                     # nginx: 4xx/5xx, 502
docker compose logs -f db                      # PostgreSQL
docker compose exec api alembic current        # версия схемы
docker compose exec db psql -U karier_user -d karier_db -c '\dt gis.*' | head
docker stats --no-stream                       # CPU/RAM контейнеров
docker system df                               # место: образы/тома/кэш сборки
```

Типичные проблемы:

| Симптом | Причина / решение |
|---|---|
| `api` циклически перезапускается, в логе `psycopg`/`connection refused` | БД ещё не готова или неверный `POSTGRES_PASSWORD`; entrypoint ждёт до 90 с — проверьте `docker compose logs db` |
| `ValueError: SECRET_KEY … короче 32` при `ENV=prod` | задайте `SECRET_KEY` ≥32 символов (это защита prod из S-1) |
| `502 Bad Gateway` на `/api/` | `api` не healthy: `docker compose ps`, логи api; после исправления `docker compose up -d` |
| Вход прошёл, но сразу разлогинивает | `COOKIE_SECURE=true` без HTTPS либо `CORS_ORIGINS` не содержит адрес сайта |
| В аудите IP nginx вместо клиента | укажите прокси в `TRUSTED_PROXIES` (S-4) |
| `413 Request Entity Too Large` | документ/фото больше `MAX_*_MB` или `client_max_body_size` в nginx |
| Время в логах не местное | задайте `TZ` в compose/образе (`Europe/Moscow` по умолчанию) |

---

## 13. TLS и внешний прокси

Рекомендуемая схема: TLS-терминация на хосте (Caddy/nginx/Traefik) → `web` на `127.0.0.1:8080`.

**Caddy (проще всего, автоматический Let's Encrypt):**

```caddyfile
karier.example.ru {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
```

**nginx на хосте:**

```nginx
server {
    listen 443 ssl http2;
    server_name karier.example.ru;
    ssl_certificate     /etc/letsencrypt/live/karier.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/karier.example.ru/privkey.pem;

    client_max_body_size 25m;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
server { listen 80; server_name karier.example.ru; return 301 https://$host$request_uri; }
```

После включения TLS в `.env`:

```dotenv
COOKIE_SECURE=true
PUBLIC_BASE_URL=https://karier.example.ru
CORS_ORIGINS=https://karier.example.ru
TRUSTED_PROXIES=172.18.0.1        # адрес шлюза docker-сети, откуда приходит X-Forwarded-For
```

Перезапуск: `docker compose up -d`. Проверка: `curl -sSI https://karier.example.ru/api/health/ready`
и в браузере — cookie `Secure`, нет предупреждений.

> Порт `8080` можно не публиковать наружу: в `docker-compose.yml` замените `ports:` на
> `127.0.0.1:${WEB_PORT:-8080}:80` — тогда сайт доступен только через TLS-прокси на хосте.

---

## 14. Чек-лист приёмки

```bash
cd /opt/karier
docker compose ps                                    # db/api/web = healthy
curl -fsS http://127.0.0.1:8080/api/health/ready     # database: ok
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/         # 200
docker compose exec api alembic current              # 0014 (head)
docker compose exec db psql -U karier_user -d karier_db -c 'select count(*) from gis.assets;'
```

- [ ] `.env` заполнен, заглушек `__` нет, права `600`, в git не попал
- [ ] `docker compose config -q` без ошибок, `build` и `up -d` прошли
- [ ] `health/ready` = ok, все контейнеры healthy
- [ ] `alembic current` = head, миграции применились при старте
- [ ] seed выполнен; `000001` входит, пароль сменён; `000000` распечатан и убран в сейф
- [ ] карта и схема открываются, питание переключается, связи отображаются
- [ ] OTP выдаётся вручную из админки, `EXPOSE_OTP_CODE=false`
- [ ] sourcemap по `/assets/*.js.map` → 404; статика отдаётся с `immutable`
- [ ] фидеры: `?feeder=ВЛ-6кВ-4` и `?feeder=ф.21К` дают разные наборы объектов
- [ ] бэкап БД и томов снят и проверен восстановлением в `karier_restore`
- [ ] TLS/прокси настроены, `COOKIE_SECURE=true`, вход по https
- [ ] при перезапуске (`down` + `up`, без `-v`) данные и файлы на месте

---

## 15. Ограничения

1. **Один карьер в API.** Разделение второго карьера сделано по фидерам внутри активного карьера
   (S-8). Отдельная запись `gis.pits` потребует выбора карьера в API — отдельная задача.
2. **Фильтр по фидеру в UI пока не выведен** (S-8 — backend): проверка через API/поле `feeders`;
   добавление селектора в реестр/схему — задача следующей волны.
3. **Один воркер API.** Для нескольких воркеров нужен общий стор rate-limit (I-41).
4. **`STORAGE_BACKEND=local`** — файлы в томах; `vercel_blob` для собственного сервера не нужен.
5. **Первый `docker compose build`** требует доступа к registry (python/node/nginx/postgres) — на
   закрытом контуре понадобится локальное зеркало образов.
6. **`docker compose down -v`** удаляет тома безвозвратно — только осознанно и только после бэкапа.
7. Инструкция проверена статически (в среде подготовки Docker отсутствовал); полный прогон на чистом
   сервере — по чек-листу §14, лог первого запуска стоит сохранить в журнале эксплуатации.
