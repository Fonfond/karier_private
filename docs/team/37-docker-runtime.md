# Docker/Compose: runtime-проверка на установленном Docker Desktop

Дата: 27.11.2026 · машина владельца · Docker **29.9.3**, Compose **v5.7.1**
Итог: **стек собирается, поднимается и работает; данные переживают restart и down/up.**

## 1. Что проверено

| Проверка | Результат |
|---|---|
`docker compose config -q` | exit 0, переменные из `.env` подхвачены |
Сборка образов `docker compose up -d --build` | `karier-api`, `karier-web` собраны; контексты без секретов |
Контейнеры | `db` healthy, `api` healthy, `web` healthy (порты: web `0.0.0.0:8080→80`; db/api наружу не опубликованы) |
Сайт через nginx | `GET http://127.0.0.1:8080/` → **200** |
Health | `GET /api/health/ready` → `database=ok` |
CSP | `default-src 'self'; object-src 'none'; frame-ancestors 'self'` |
Статика | `.js.map` → **404** (sourcemap не отдаётся) |
Вход | `000001/admin` → 200, токен; после `restart api web` — снова 200 |
Реестр/граф | `/api/assets` total=27, `/api/topology/graph` nodes=27 |
Браузер (Edge/CDP) | вход, дашборд, схема: **27 узлов / 24 ребра**, console errors 0, API ≥400 из UI 0 |
PWA | `isSecureContext=true`, `serviceWorker` доступен на `localhost` |
Персистентность | `docker compose restart api web` → health/вход ок; `down` → `up` (без `-v`) → 27 объектов на месте |

## 2. Найден и исправлен дефект деплоя

Первая попытка `up` падала: `db` уходил в `Restarting`, лог:

> in 18+, these Docker images ... there appears to be PostgreSQL data in:
> `/var/lib/postgresql/data (unused mount/volume)`

**Причина:** образ `postgres:18` изменил структуру тома — данные теперь в `/var/lib/postgresql/<major>/docker`, а не в `/var/lib/postgresql/data`. Монтирование старого пути ломает инициализацию.

**Исправление:** `docker-compose.yml` → `pgdata:/var/lib/postgresql`. После `down -v` + `up` стек поднялся штатно.

## 3. Первичное наполнение (как в docs/55 §7)

```powershell
docker compose exec api python seed.py               # 000001/admin, 000002/operator123
docker compose exec api python seed_gis.py           # карьер, подложка, типы, 16 объектов
docker compose exec api python seed_topology.py      # 3 линии, 25 связей
docker compose exec api python seed_schema_blocks.py # 13 шаблонов блоков
```
Итог: 27 объектов, 20 типов, 13 блоков, 3 линии. `seed_break_glass.py` для локального стенда не запускался (печатает аварийный пароль — только для боевого сервера).

## 4. Настройки `.env` для локальной проверки

- `POSTGRES_PASSWORD`, `SECRET_KEY` — случайные (файл `.env` в `.gitignore`, старый бэкап убран из репозитория в `.local/env-backups/`);
- `COOKIE_SECURE=false` — для локального http://localhost; **на сервере с HTTPS вернуть `true`**;
- `PUBLIC_BASE_URL=http://localhost:8080`, `CORS_ORIGINS` пуст (same-origin через nginx);
- `WEB_PORT=8080` (dev-стенд на 5174/8001 не конфликтует).

## 5. Ограничения

1. Локальная проверка — **http://localhost**; для доступа по LAN/интернету нужен HTTPS (reverse-proxy + `COOKIE_SECURE=true`), иначе PWA/офлайн и refresh-cookie не работают.
2. Демо-сиды наполняют базу примерами; на боевом сервере — только `seed.py` + свои справочники, `000003` удалить/заблокировать.
3. Образы собраны локально (`karier-api:latest`, `karier-web:latest`); на сервере сборка повторится из тех же Dockerfile.
4. Docker Desktop на Windows — только для проверки; на сервере ставится Docker Engine (docs/55 §2).

## 6. Команды эксплуатации

```powershell
docker compose ps
docker compose logs -f api
docker compose restart api web
docker compose down          # данные в томах сохраняются
docker compose up -d
docker compose down -v       # ВНИМАНИЕ: удаляет БД и файлы томов
```
