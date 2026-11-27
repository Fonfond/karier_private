# Развёртывание: дерево проекта, что заливать и какие секреты вводить

Версия 1.0 · 24.11.2026 · проект: `C:\karier\karier`

## 1. Два контура

| Контур | Что это | Как запускается |
|---|---|---|
| Стенд (сейчас) | Windows-ПК, Vite-dev на 5174 + API 8001 + портативный PostgreSQL 18 | `stack-start.cmd` → `C:\karier\.local\stack.ps1` |
| Прод (сервер) | Linux, nginx раздаёт собранный фронтенд и проксирует `/api`, API — uvicorn под systemd, PostgreSQL локально | см. §6 |

Отличаются только `.env`, способом отдачи статики и HTTPS. Код один и тот же.

## 2. Дерево проекта

```
C:\karier\
├─ karier\                        ← сам проект (это и заливается)
│  ├─ backend-v2\                 ← ДЕЙСТВУЮЩИЙ бэкенд (FastAPI)
│  │  ├─ app\
│  │  │  ├─ main.py               вход приложения: роутеры, middleware, обработчики ошибок
│  │  │  ├─ core\
│  │  │  │  ├─ config.py          ВСЕ настройки из .env (см. §4)
│  │  │  │  ├─ security.py        Argon2id, JWT, TOTP
│  │  │  │  ├─ errors.py          единый формат problem+json
│  │  │  │  ├─ rate_limit.py      лимиты входов/регистраций
│  │  │  │  └─ ids.py             генерация кодов объектов
│  │  │  ├─ db\                   движок SQLAlchemy, сессии, Base
│  │  │  ├─ models\               таблицы: auth, gis, ops, audit, sync, topology
│  │  │  ├─ schemas\              Pydantic-контракты API
│  │  │  ├─ services\             бизнес-логика (27 модулей)
│  │  │  │  ├─ auth.py            вход, refresh, 2FA, блокировки
│  │  │  │  ├─ gis.py             объекты, типы, порты, границы карты
│  │  │  │  ├─ links.py           связи, проверка напряжения/направления
│  │  │  │  ├─ topology.py        граф питания, power-path, проверки
│  │  │  │  ├─ schema_blocks.py   библиотека блоков, ячейки, контуры
│  │  │  │  ├─ schema_graph.py    граф схемы для редактора и снимков
│  │  │  │  ├─ schema_snapshots.py снимки/публикация схемы
│  │  │  │  ├─ poles.py           опоры и ВЛ
│  │  │  │  ├─ storage.py         файлы: local или Vercel Blob
│  │  │  │  ├─ reports.py         XLSX/PDF-отчёты
│  │  │  │  └─ notify.py          коды/письма (консоль или Telegram)
│  │  │  └─ api\
│  │  │     ├─ deps.py            зависимости (текущий сотрудник, права)
│  │  │     ├─ middleware.py      request-id, аудит, время ответа
│  │  │     └─ routers\           18 роутеров = 117 операций API
│  │  │        auth, gis, links, topology, schema_blocks, defects,
│  │  │        inspections, media, documents, reports, employees,
│  │  │        map_layers, sync, audit, moves, me, health
│  │  ├─ alembic\                 14 миграций (versions\00NN_*.py)
│  │  ├─ tests\                   pytest: 162 теста (conftest жёстко требует тестовую БД)
│  │  ├─ seed.py                  роли, права и 3 демо-сотрудника (первый запуск)
│  │  ├─ seed_gis.py, seed_topology.py, seed_schema_blocks.py — демо-данные
│  │  ├─ seed_break_glass.py      аварийная учётка 000000 (пароль + TOTP в консоль)
│  │  ├─ reset_break_glass.py     перевыпуск секретов аварийного доступа
│  │  ├─ tools\db_admin.py        обслуживание БД
│  │  ├─ var\documents, var\media загруженные файлы (в git не входят)
│  │  ├─ requirements.txt         зависимости Python
│  │  ├─ alembic.ini              конфиг миграций
│  │  └─ .env.example             шаблон окружения → скопировать в .env
│  │
│  ├─ src-v2\                     ← ДЕЙСТВУЮЩИЙ фронтенд (React + Vite)
│  │  ├─ src\
│  │  │  ├─ main.tsx, App.tsx     точка входа, маршруты
│  │  │  ├─ auth\                 AuthProvider (JWT + refresh-cookie), guards
│  │  │  ├─ pages\                16 страниц: Login, Mfa, Register, Dashboard,
│  │  │  │                        Map, Registry, Types, Cables, Defects,
│  │  │  │                        Inspection, Employees, Audit, Sync, Profile,
│  │  │  │                        AssetDeepLink, Home
│  │  │  ├─ components\
│  │  │  │  ├─ map\MapView.tsx    карта (Leaflet CRS.Simple)
│  │  │  │  ├─ map\SchemaView.tsx редактор однолинейной схемы (~2500 строк)
│  │  │  │  ├─ map\AddToSchemaPanel.tsx, BulkCellsDialog.tsx, SnapshotsPanel.tsx
│  │  │  │  ├─ asset\…            карточка объекта: паспорт, фото, документы, история
│  │  │  │  └─ …                  BottomNav, BottomSheet, PhotoDialog, QrScanner, Tour
│  │  │  ├─ lib\
│  │  │  │  ├─ api.ts             fetch-обёртка, ApiError, refresh
│  │  │  │  ├─ gis.ts             контракты API + POWER_COLOR
│  │  │  │  ├─ opsApi.ts, dashboard.ts, sync.ts, outbox.ts, offlineDocs.ts
│  │  │  │  └─ dxf.ts, photo.ts   DXF-экспорт, сжатие фото
│  │  │  └─ index.css             стили (Tailwind)
│  │  ├─ public\                  PWA: manifest, иконки, sw.js, подложка карты
│  │  ├─ dist\                    ГОТОВАЯ сборка (npm run build)
│  │  ├─ vite.config.ts           dev-сервер + прокси /api → 127.0.0.1:8001
│  │  ├─ vite.test.config.mjs     изолированный стенд для браузерных проверок (не для прода)
│  │  ├─ vercel.json              заголовки/rewrites для варианта Vercel
│  │  └─ package.json             npm run dev / build / typecheck / test
│  │
│  ├─ docs\                       ТЗ, модель данных, отчёты (27 МБ, на сервер не обязательно)
│  │  ├─ 50-tz-as-built-and-report.docx   главный ТЗ-отчёт для заказчика
│  │  └─ 51…54-*-report.md        отчёты по функциям
│  └─ README.md                   быстрый старт
│
├─ .local\                        ← СЛУЖЕБНОЕ, на сервер НЕ заливать
│  ├─ pg18\                       портативный PostgreSQL Windows
│  ├─ backups\                    дампы БД (секретные данные)
│  ├─ logs\                       api.log, vite.log, pg-server.log
│  ├─ browser\                    puppeteer-проверки
│  ├─ stack.ps1, run-api.cmd, run-web.cmd, run-pg.cmd
│  └─ reset-test-db.ps1, show-operator-totp.py
├─ db-backup.cmd, stack-*.cmd, test-db-reset.cmd, firewall-allow.cmd
└─ backups\                       (если создавались вручную)
```

**Легаси, не заливать:** `karier\backend\` (86 МБ, прототип), `karier\src\` + `public\` +
`index.html` + `vite.config.ts` в корне, `.vercel\`, корневые `1.js`, `2.js`, `addCablesInWork.js`,
`.venv\`, `venv\`, `node_modules\`.

## 3. Что именно заливать на сервер

### Вариант А — собрать на сервере (рекомендую)

| Что | Откуда | Куда на сервере |
|---|---|---|
| Бэкенд | `backend-v2\` **без** `venv\`, `var\`, `__pycache__`, `.pytest_cache`, `venv.broken-*` | `/opt/karier/backend/` |
| Фронтенд (исходники) | `src-v2\` **без** `node_modules\`, `dist\` | `/opt/karier/frontend-src/` |
| Документация (по желанию) | `docs\` | `/opt/karier/docs/` |

На сервере: `python -m venv venv && venv/bin/pip install -r requirements.txt`,
`npm ci && npm run build`, готовую `dist/` положить в `/opt/karier/frontend/`.

### Вариант Б — залить готовое

`backend-v2\` (как выше) + `src-v2\dist\` (7,6 МБ) в `/opt/karier/frontend/`.
Node на сервере тогда не нужен.

### Что НЕ заливать

- `.env` с рабочими секретами (создать на сервере, `chmod 600`);
- `.local\`, `backups\`, `*.dump` — там данные и пароли;
- `venv\`, `node_modules\`, `__pycache__`, `.pytest_cache`;
- `backend\`, `src\` — старый прототип;
- `var\documents`, `var\media` — переносятся отдельно, если нужны загруженные файлы.

Размер полезного: бэкенд ≈ 1,5 МБ, фронтенд-исходники ≈ 0,5 МБ, сборка ≈ 7,6 МБ.

## 4. Секреты и переменные окружения

Файл: `backend-v2/.env` (приложение читает `backend-v2/.env`, затем `.env`).
Шаблон — `backend-v2/.env.example`. В git `.env` не попадает.

### Обязательные в проде

| Переменная | Значение в проде | Как получить |
|---|---|---|
| `ENV` | `prod` | — |
| `DEBUG` | `false` | — |
| `DATABASE_URL` | `postgresql+psycopg://karier_user:ПАРОЛЬ@127.0.0.1:5432/karier_db` | задаётся при создании роли БД |
| `SECRET_KEY` | 48+ случайных символов | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `true` (только HTTPS) | — |
| `CORS_ORIGINS` | `https://karier.example.ru` | ваш домен |
| `PUBLIC_BASE_URL` | `https://karier.example.ru` | QR в паспорте объекта |
| `EXPOSE_OTP_CODE` | `false` | иначе коды 2FA видны в ответах API |
| `CONSOLE_NOTIFICATIONS` | `false` | коды не печатаются в лог |

### Секреты уровня «ввести руками в интерфейсе»

| Что | Где взять | Куда вводить |
|---|---|---|
| Пароль администратора `000001` | задаётся при `python seed.py` (временный `admin`) | экран входа → сразу сменить в «Профиле» |
| Пароль оператора `000002` | `seed.py` (`operator123`) | — |
| TOTP-секрет `000002` (base32) | `seed.py` печатает ASCII-QR и секрет | приложение-аутентификатор (Google Authenticator / Aegis) |
| Аварийный доступ `000000` | `venv/bin/python seed_break_glass.py` — печатает пароль, TOTP-секрет, QR | распечатать, запечатать, хранить в сейфе |
| Пароль БД `karier_user` | при `CREATE ROLE` | только в `.env` |
| Пароль PostgreSQL-суперпользователя | при установке PostgreSQL | хранить отдельно |

### Необязательные, но полезные

| Переменная | Зачем | Прод-значение |
|---|---|---|
| `DOCUMENTS_DIR` | паспорта/документы | `/opt/karier/data/documents` |
| `MEDIA_DIR` | фото обходов | `/opt/karier/data/media` |
| `STORAGE_BACKEND` | `local` или `auto` (Vercel Blob при токене) | `local` |
| `BLOB_READ_WRITE_TOKEN` | только если медиа в Vercel Blob | токен из Vercel |
| `PDF_FONT_PATH` | кириллица в PDF | `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` |
| `ACCESS_TOKEN_TTL_MIN` / `REFRESH_TOKEN_TTL_DAYS` | время жизни токенов | 15 / 30 |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | защита входа | 20 |
| `MAX_DOCUMENT_MB` / `MAX_PHOTO_MB` | лимиты файлов | 25 / 15 |

Минимальный `.env` для сервера:

```ini
ENV=prod
DEBUG=false
DATABASE_URL=postgresql+psycopg://karier_user:СМЕНИТЬ_ПАРОЛЬ@127.0.0.1:5432/karier_db
SECRET_KEY=СМЕНИТЬ_НА_48_СЛУЧАЙНЫХ_СИМВОЛОВ
COOKIE_SECURE=true
CORS_ORIGINS=https://karier.example.ru
PUBLIC_BASE_URL=https://karier.example.ru
EXPOSE_OTP_CODE=false
CONSOLE_NOTIFICATIONS=false
DOCUMENTS_DIR=/opt/karier/data/documents
MEDIA_DIR=/opt/karier/data/media
STORAGE_BACKEND=local
PDF_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
```

## 5. Установка на Linux (Ubuntu 22.04/24.04)

```bash
# 1. Пакеты
sudo apt update && sudo apt install -y python3-venv python3-pip postgresql nginx nodejs npm

# 2. Каталоги
sudo mkdir -p /opt/karier/{backend,frontend,frontend-src,data/documents,data/media}
sudo chown -R $USER:$USER /opt/karier

# 3. Код (scp/rsync/архив) — backend-v2 без venv, src-v2 без node_modules
rsync -av --exclude venv --exclude var --exclude __pycache__ backend-v2/ /opt/karier/backend/
rsync -av --exclude node_modules --exclude dist src-v2/ /opt/karier/frontend-src/

# 4. Python-окружение
cd /opt/karier/backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 5. Фронтенд
cd /opt/karier/frontend-src && npm ci && npm run build
cp -r dist/* /opt/karier/frontend/

# 6. База
sudo -u postgres psql -c "CREATE ROLE karier_user LOGIN PASSWORD 'СМЕНИТЬ_ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE karier_db OWNER karier_user;"

# 7. .env (см. §4) и миграции
cd /opt/karier/backend
cp .env.example .env && nano .env && chmod 600 .env
venv/bin/alembic upgrade head

# 8. Первичные учётные записи (один раз)
venv/bin/python seed.py                 # роли/права + 000001, 000002, 000003
venv/bin/python seed_break_glass.py     # 000000: пароль и QR — в сейф
```

`systemd` (`/etc/systemd/system/karier-api.service`):

```ini
[Unit]
Description=Karier GIS API
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/karier/backend
EnvironmentFile=/opt/karier/backend/.env
ExecStart=/opt/karier/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

`nginx` (`/etc/nginx/sites-available/karier`):

```nginx
server {
    listen 80;
    server_name karier.example.ru;
    root /opt/karier/frontend;
    index index.html;
    client_max_body_size 30m;

    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location = /sw.js {
        add_header Cache-Control "no-cache";
        try_files $uri =404;
    }

    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location / {
        try_files $uri /index.html;
    }
}
```

Затем `sudo ln -s /etc/nginx/sites-available/karier /etc/nginx/sites-enabled/`,
`sudo nginx -t && sudo systemctl reload nginx`, `sudo systemctl enable --now karier-api`.
HTTPS — `sudo certbot --nginx -d karier.example.ru` (после этого `COOKIE_SECURE=true` обязателен).

## 6. Проверка после установки

```bash
curl -s https://karier.example.ru/api/health/ready      # {"database":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://karier.example.ru/          # 200
curl -s -o /dev/null -w '%{http_code}\n' https://karier.example.ru/docs      # 200
```

В браузере: вход `000001` → смена пароля → «Типы» (справочник) → «Реестр» (создание объекта)
→ «Карта» → «Схема» → PWA-установка с телефона.

## 7. Обновление версии, бэкап, откат

```bash
# бэкап перед обновлением
pg_dump -Fc -h 127.0.0.1 -U karier_user karier_db > /opt/karier/backup-$(date +%F).dump

# обновление
rsync -av backend-v2/ /opt/karier/backend/ --exclude venv --exclude .env
cd /opt/karier/backend && venv/bin/pip install -r requirements.txt && venv/bin/alembic upgrade head
cd /opt/karier/frontend-src && npm ci && npm run build && cp -r dist/* /opt/karier/frontend/
sudo systemctl restart karier-api

# откат кода: вернуть предыдущий архив/коммит, alembic downgrade -1
```

Перед каждым обновлением: `pytest -q` на тестовой БД (`test-db-reset` + прогон), затем бэкап.

## 8. Чек-лист безопасности

- [ ] `SECRET_KEY` не равен значению из примера и не хранится в git;
- [ ] `ENV=prod`, `DEBUG=false`, `COOKIE_SECURE=true`;
- [ ] `EXPOSE_OTP_CODE=false`, `CONSOLE_NOTIFICATIONS=false`;
- [ ] `.env` с правами `600`, владелец — сервисный пользователь;
- [ ] API слушает только `127.0.0.1` (наружу — nginx);
- [ ] пароль `000001` сменён, 2FA включена; `000002` и `000000` проверены;
- [ ] бэкап БД настроен по расписанию (cron `pg_dump`), дампы — вне веб-корня;
- [ ] `var/documents` и `var/media` не доступны напрямую из nginx (только через API).
