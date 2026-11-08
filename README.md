# Карьер · Электроснабжение

Система управления электроснабжением карьера: карта, топология питания, обходы, фото с метаданными,
дефекты, документы, офлайн-режим и синхронизация с разрешением конфликтов.

| Слой | Технологии |
|---|---|
| Фронтенд | React 18, TypeScript, Vite, TailwindCSS, Leaflet (CRS.Simple), React Flow, PWA |
| Бэкенд | Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, psycopg 3 |
| Безопасность | Argon2id, TOTP 2FA, httpOnly refresh-cookie, RBAC, append-only аудит |
| Хранилище | локальный диск (dev) или Vercel Blob (prod) через абстракцию `storage` |

Документация: [`docs/README.md`](docs/README.md) — ТЗ, модель данных, UI/UX, отчёты по спринтам 1–7.
Приложение: `src-v2/` (новый интерфейс), `backend-v2/` (новый API).

---

## 1. Быстрый старт (локально)

### 1.1. База данных

```powershell
# PostgreSQL 16+ должен быть запущен
$env:PGPASSWORD="..."
psql -h 127.0.0.1 -U postgres -c "CREATE ROLE karier_user LOGIN PASSWORD 'karier';"
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE karier_db OWNER karier_user;"
```

### 1.2. Бэкенд

```powershell
cd backend-v2

# Python 3.11+ (проверено на 3.12–3.14)
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt

Copy-Item .env.example .env
# отредактируйте DATABASE_URL, SECRET_KEY, CORS_ORIGINS

.\venv\Scripts\python -m alembic upgrade head
.\venv\Scripts\python seed.py          # роли, права, администратор 000001
.\venv\Scripts\python seed_gis.py      # карьер, подложка, типы, 16 объектов
.\venv\Scripts\python seed_topology.py # секции, ячейки, линии, связи
.\venv\Scripts\python seed_demo.py     # демо: фото, дефекты, обход, перемещения

.\venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

API: http://127.0.0.1:8001/docs

### 1.3. Фронтенд

```powershell
cd src-v2
npm install
npm run dev        # http://localhost:5174, /api проксируется на 8001
```

Учётные записи после сидов:

| Табельный | Пароль | Роль |
|---|---|---|
| 000001 | admin | администратор |
| 000002 | operator123 | оператор (2FA включена) |
| 000003 | — | регистрация по коду (демо закрытой регистрации) |

---

## 2. Тесты и проверки

```powershell
cd backend-v2
.\venv\Scripts\python -m pytest -q        # 50 тестов
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1   # сквозной сценарий

cd ..\src-v2
npm test                 # юнит-тесты водяного знака (vitest)
npm run typecheck        # tsc --noEmit
npm run build            # production-сборка
```

---

## 3. Деплой

### 3.1. Бэкенд (Render / Railway / любой VPS)

1. Создайте PostgreSQL (Render PostgreSQL, Neon, Supabase, RDS) и получите `DATABASE_URL`
   вида `postgresql+psycopg://user:pass@host:5432/db?sslmode=require`.
2. Задеплойте репозиторий как Python-сервис:
   * **Build command:** `pip install -r backend-v2/requirements.txt`
   * **Start command:** `cd backend-v2 && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   * **Root directory:** `backend-v2` (или корень с путями выше).
3. Переменные окружения (минимум):

```env
ENV=prod
SECRET_KEY=<32+ случайных символа>
DATABASE_URL=postgresql+psycopg://...
COOKIE_SECURE=true
CORS_ORIGINS=https://<ваш-домен-vercel>
PUBLIC_BASE_URL=https://<ваш-домен-vercel>
STORAGE_BACKEND=vercel_blob
BLOB_READ_WRITE_TOKEN=<токен Vercel Blob>
BLOB_PUBLIC_BASE=https://<store-id>.public.blob.vercel-storage.com
EXPOSE_OTP_CODE=false
```

4. Один раз выполните сиды (Render Shell):

```bash
python seed.py && python seed_gis.py && python seed_topology.py && python seed_demo.py
```

5. **Шрифт для PDF.** На Linux нужен TTF с кириллицей. DejaVu обычно уже есть:
   `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` — сервис найдёт его сам.
   Иначе укажите `PDF_FONT_PATH=/path/to/font.ttf` или положите файл в `backend-v2/assets/fonts/DejaVuSans.ttf`.

### 3.2. Фронтенд (Vercel)

1. Импортируйте репозиторий, **Root Directory** = `src-v2`.
2. Framework preset: **Vite**, Build: `npm run build`, Output: `dist` (уже в `src-v2/vercel.json`).
3. Переменная окружения: `VITE_API_URL` — не нужна, если API на том же домене через rewrites.
   При отдельном домене API настройте прокси Vercel:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://<api-домен>/api/:path*" },
    { "source": "/((?!api/).*)", "destination": "/index.html" }
  ]
}
```

4. В `src-v2/vercel.json` уже заданы security-заголовки: CSP, HSTS, `X-Frame-Options: SAMEORIGIN`,
   `Permissions-Policy` (камера/геолокация — только свой домен).

> Cookie с `SameSite=Lax` и `Secure` работают, если фронтенд и API находятся на одном сайте
> (например, `app.example.ru` и `api.example.ru` — один registrable domain). Разные домены
> потребуют `SameSite=None` и HTTPS на обоих.

### 3.3. Чек-лист перед продом

- [ ] `SECRET_KEY` заменён на случайный (32+ символа), старый нигде не используется
- [ ] `COOKIE_SECURE=true`, приложение открывается только по HTTPS
- [ ] `CORS_ORIGINS` содержит только реальные домены
- [ ] `EXPOSE_OTP_CODE=false`, Telegram-бот или выдача кодов вручную настроены
- [ ] Восстановление из бэкапа проверено (RPO ≤ 15 мин, RTO ≤ 4 ч)
- [ ] Администратор сменил временный пароль `admin`
- [ ] Второй фактор включён у всех администраторов
- [ ] Проверены выгрузки Excel/PDF и установка PWA на телефон
- [ ] Выпущен и запечатан в сейф аварийный доступ (см. раздел «Аварийный доступ»)

---

## 3.4. Аварийный доступ (break glass)

Учётная запись `000000` с ролью `admin` — резервный вход на случай, когда обычные
администраторы недоступны (забыли пароль, потеряли телефон, уволились).
Пароль и TOTP-секрет генерируются скриптом и **не хранятся в системе в открытом виде**.

### Выпуск (один раз, при внедрении)

```powershell
cd backend-v2
.\venv\Scripts\python seed_break_glass.py
```

Скрипт печатает:

* пароль из 28 символов (буквы, цифры, спецсимволы);
* TOTP-секрет и `otpauth://`-ссылку;
* ASCII QR-код для добавления в Google Authenticator / Aegis.

**Процедура хранения:**

1. Распечатать лист целиком (пароль, секрет, QR).
2. Запечатать в конверт, подписать, поставить дату.
3. Конверт №1 — в сейф службы главного энергетика, конверт №2 — у директора.
4. Не сохранять файл на компьютере, не пересылать в мессенджерах и почте.
5. Доступ к конвертам — только по распоряжению директора, с записью в журнале выдачи.

### Использование

1. Вход: табельный `000000` → пароль из конверта → код из приложения.
2. Выполнить только те действия, которые нужны для восстановления доступа
   (например, разблокировать администратора или сбросить ему пароль).
3. Сразу после — перевыпустить секреты (см. ниже) и вернуть конверт в сейф.

Все действия этого аккаунта помечаются в журнале: в `audit.audit_log` у записи
есть `payload.break_glass = true`. Директор может отфильтровать журнал по
табельному `000000` и увидеть, когда и что делал аварийный доступ.

### Перевыпуск и блокировка

```powershell
cd backend-v2
.\venv\Scripts\python reset_break_glass.py            # новые пароль и TOTP
.\venv\Scripts\python reset_break_glass.py --disable  # заблокировать аккаунт
```

Перевыпуск отзывает все сессии аккаунта и сбрасывает защиту TOTP от повторного
использования кода. Старые пароль и секрет перестают действовать сразу.

### Защита от удаления

* Через интерфейс аккаунт удалить, заблокировать, уволить или изменить его роль
  **нельзя** — API возвращает `400 employee.break_glass_protected`.
* В списке сотрудников он помечен бейджем «аварийный», кнопки действий скрыты.
* Обойти защиту можно только прямым SQL или скриптом `reset_break_glass.py`
  (это осознанное требование: аварийный доступ не должен исчезнуть случайно).

### Если аварийный доступ скомпрометирован

1. `reset_break_glass.py --disable` — блокирует аккаунт и отзывает сессии.
2. Проверить журнал: фильтр по табельному `000000`, поле `break_glass`.
3. Сменить `SECRET_KEY` и перевыпустить аварийный доступ после разбора.

---

## 4. Структура репозитория

```
backend-v2/        FastAPI, SQLAlchemy, Alembic, сиды, тесты
  app/api/         роутеры (auth, gis, topology, ops, sync, reports)
  app/models/      SQLAlchemy: auth, gis, ops, sync, audit
  app/services/    доменная логика: топология, синхронизация, отчёты, хранилище
  alembic/         миграции 0001–0005
  tests/           pytest, 50 тестов
src-v2/            React + Vite + Tailwind PWA
  src/pages/       Дашборд, Карта, Реестр, Обход, Дефекты, Справочник, Синхронизация
  src/lib/         API, фото и водяной знак, офлайн-очередь, синхронизация
docs/              ТЗ, модель данных, UI/UX, отчёты по спринтам
```

---

## 5. Возможности

* **Дашборд** — метрики «под напряжением / обесточено», дефекты по критичности, обходы за неделю,
  состояние «кукушек», графики статусов и дефектов.
* **Карта** — подложка в метрах, маркеры по типам, шторка объекта, соединение портов, история перемещений.
* **Схема** — однолинейная схема из графа связей, автоматическая раскладка, пунктир у разомкнутых связей.
* **Топология** — расчёт питания обходом графа, заземление, журнал переключений, внутренняя структура РУ.
* **Обходы и дефекты** — отметки «норма/дефект», фото с водяным знаком, закрытие только с фото «после».
* **Документы** — PDF/Word/Excel, офлайн-кэш, просмотр в приложении.
* **Офлайн** — очередь в IndexedDB, Service Worker, Background Sync, разрешение конфликтов LWW.
* **Отчёты** — Excel (реестр, дефекты, переключения, обходы), PDF-паспорт объекта с QR и фото.
* **PWA** — установка на телефон, работа без сети, тёмная тема.

---

## 6. Лицензия и данные

Проект внутренний. Демо-данные (`seed_demo.py`) синтетические и не содержат реальных
персональных данных.
