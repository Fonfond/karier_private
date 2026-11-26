# 17 — S-5: ручная выдача OTP, SVG/CSP, авторизация подложки

Дата: 2026-11-26, 00:20–01:10 (локальное время машины, UTC+08:00).
Кто: `edit-reviewer`. Задача t16 (implementation), проект `C:\karier\karier`.
Основание: аудит (R-отчёт) и приёмка V1/V1b — код регистрации уходил в ответе API и в
журнал, подложка карты отдавалась без авторизации, документы принимали SVG.

## Что сделано (сводка)

| # | Проблема | Решение |
|---|---|---|
| 1 | `debug_code` в ответе `register/start`, коды в логах/stdout | код не возвращается и не печатается; выдаёт администратор |
| 2 | Нет способа выдать код безопасно | `POST /api/employees/{id}/otp` (admin): одноразовый код на 10 минут, возврат один раз, в БД только хеш |
| 3 | SVG принимался как документ (хранимый XSS) | `image/svg+xml` убран из белого списка + проверка magic bytes и разметки |
| 4 | Небезопасные типы отдавались `inline` с mime из БД | inline только pdf/png/jpeg/webp, остальное — `octet-stream` + `attachment` |
| 5 | Нет CSP | `default-src 'self'; object-src 'none'; frame-ancestors 'self'` в dev и prod |
| 6 | Подложка карты публична | `GET /api/map/layers/{id}/image` требует авторизации, `Cache-Control: private, no-store`; фронт качает через Bearer → blob URL |
| 7 | Не было интерфейса выдачи | Экран «Сотрудники → Выдать код» (кнопка, модалка, таймер, копирование) |

## 1. OTP: как администратор выдаёт код

`app/services/auth.py`:

* `REGISTRATION_CODE_TTL_MIN = 10` — фиксированный срок (не зависит от `.env`);
* `issue_registration_code(db, employee)`:
  * отказывает, если сотрудник уже зарегистрирован (409) или неактивен (409);
  * гасит все прежние невыкупленные коды (`consumed_at = now()`) — действующим остаётся
    только новый;
  * генерирует 6-значный код (`new_numeric_code(6)`), кладёт в `auth.onboarding_tokens`
    **только `code_hash`** и `expires_at = now() + 10 минут`;
  * пишет аудит `auth.register.code_issued` с текстом «Код выдан администратором, срок 10 мин»
    и `payload={"channel": "manual"}` — **без кода**;
  * возвращает код вызывающему один раз (в ответе HTTP), в БД открытого кода нет.

`app/api/routers/employees.py`:

```
POST /api/employees/{employee_id}/otp      # require_admin
201 { "code": "482913", "tab_no": "000042", "expires_at": "...Z", "expires_in": 600 }
```

`start_registration` больше не генерирует код и не возвращает `debug_code`: ответ
`{delivery, delivery_target: null, expires_in: <остаток жизни выданного кода или 0>,
next_step: "code_required"}`. Регистрация (`register/verify`) принимает только код,
выданный администратором: нет токена — 400 `auth.code_expired`; >5 попыток — 429
(логика сохранилась).

**Что видит сотрудник:** экран регистрации просит код; сам код ему передаёт администратор
лично или по защищённому каналу. Восстановить код из системы нельзя — в БД только хеш.

**Аудит:** `auth.register.code_issued` (факт выдачи, срок, канал) — без кода;
`auth.register.code_verified` (успешная проверка), `auth.register.bad_code` (неверная попытка).

## 2. Удаление утечек кода

* `app/services/notify.py` — код больше не пишется ни в `logger`, ни в stdout:
  `send_otp_code` логирует только канал и маску адреса, `_print_banner` печатает
  «код выдан» без значения. Параметр `code` оставлен для совместимости и явно
  отбрасывается (`del code`), чтобы никто не начал логировать его снова.
* `app/schemas/auth.py` — из `RegisterStartOut` удалено поле `debug_code`;
  `app/schemas/employee.py` — `InviteOut` больше не содержит `debug_code`
  (вместо него `issued: bool`), добавлена схема `OtpIssueOut`.
* `app/core/config.py` — `EXPOSE_OTP_CODE: bool = False` (deprecated: флаг больше ни на что
  не влияет) и ошибка конфигурации при `ENV=prod` + `EXPOSE_OTP_CODE=true`.

## 3. `resend_invite`: изменение контракта

`POST /api/employees/{id}/resend-invite` раньше выдавал код и возвращал его в `debug_code`.
Теперь он **не выдаёт и не возвращает код** — только состояние:

```
200 { "delivery": "telegram", "expires_in": 437, "issued": true }
```

Код выдаётся исключительно через `POST /{id}/otp` (и показывается администратору один раз).
Так у администратора нет двух конкурирующих способов, а старый «дебажный» контракт закрыт.

## 4. SVG и magic bytes

`app/services/documents.py`:

* `image/svg+xml` удалён из `ALLOWED_MIME` (MIME → 415 `document.bad_type`);
* добавлена проверка содержимого (первые 1024 байта):
  * `<svg` / `<?xml … <svg` → 415 `document.svg_not_allowed` — независимо от заявленного MIME;
  * сигнатуры: `%PDF`, `\x89PNG\r\n\x1a\n`, `\xff\xd8\xff`, `RIFF…WEBP` (с проверкой
    `head[8:12] == "WEBP"`), `PK\x03\x04` (docx/xlsx/zip), `\xd0\xcf\x11\xe0` (doc/xls);
    несовпадение → 422 `document.bad_content`.

Отдача (`app/api/routers/documents.py`): `SAFE_INLINE_MIME = {pdf, png, jpeg, webp}` — только
они отдаются `inline` с настоящим MIME; всё остальное (включая старые записи с
`mime=image/svg+xml`) — `application/octet-stream` + `Content-Disposition: attachment`.
Плюс уже включённый `X-Content-Type-Options: nosniff`.

## 5. CSP

`app/main.py` (middleware `security_headers`, одинаково в dev и prod):

```
Content-Security-Policy: default-src 'self'; object-src 'none'; frame-ancestors 'self'
```

Для SPA-страниц (Vite в dev, nginx в prod) тот же заголовок должен выставлять reverse-proxy —
это задача конфигурации развёртывания (Docker/nginx, F-1/F-2), в коде приложения её нет.

## 6. Подложка карты

* `app/api/routers/map_layers.py` — `GET /api/map/layers/{layer_id}/image` теперь под
  `Depends(current_user)` (401 без токена) и отдаёт `Cache-Control: private, no-store`
  вместо публичного суточного кеша.
* Фронтенд: `lib/api.ts` получил `requestRaw` + `requestBlob` (та же логика 401/refresh,
  что и у JSON-запросов, но без парсинга JSON); `lib/gis.ts` — `layerImageObjectUrl(url)`
  (скачивает blob и создаёт object URL); `MapView.tsx` грузит подложку в `useEffect`,
  кладёт blob URL в состояние и вызывает `URL.revokeObjectURL` при размонтировании/смене
  подложки. Пока картинка не загрузилась, карта показывается без подложки (маркеры и связи
  видны).

## 7. Экран «Сотрудники → Выдать код»

`src-v2/src/pages/EmployeesPage.tsx`:

* у сотрудника без пароля появилась кнопка **«Выдать код»** (primary);
* действие `act('otp')` вызывает `api.issueOtp(id)` и открывает модалку
  `OtpModal`: ФИО и табельный, крупный 6-значный код, обратный отсчёт «Действует 9:58»
  (от `expires_in`), предупреждение «код показывается один раз, восстановить нельзя»,
  кнопки «Скопировать» (clipboard) и «Закрыть»;
* код живёт только в состоянии модалки, ни в `localStorage`, ни в запросах не кэшируется;
  при закрытии модалки значение теряется;
* `api.resendInvite` больше не используется в UI (оставлен в клиенте для статуса).

## 8. Тесты

| Файл | Что проверяет |
|---|---|
| `tests/test_auth_api.py` | `register/start` без кода и без `debug_code`; выдача кода админом (201, 600 с); регистрация выданным кодом; повторная выдача гасит прежний; использованный и истёкший код → 400; `otp` требует admin (401/403); `resend-invite` не отдаёт код |
| `tests/test_sprint12_api.py` | CSP присутствует в ответе API; подложка: 401 без токена, `Cache-Control: private, no-store` с токеном |
| `tests/test_documents_security.py` (новый) | SVG по MIME → 415; SVG под видом PNG → 415/422; PDF с чужим содержимым → 422; старая запись `image/svg+xml` отдаётся как `octet-stream` + `attachment` |

## 9. Проверки

| Команда | Результат |
|---|---|
| `pytest -q tests/test_auth_api.py tests/test_sprint12_api.py tests/test_documents_security.py` | **22 passed**, 17.84 s, exit 0 |
| `pytest -q` (полный набор, один прогон) | _см. §10 — фактические числа_ |
| `npm run typecheck` (`tsc -b --noEmit`) | exit 0 |
| `npm run build` (`tsc -b && vite build`) | exit 0, 6.87 s (warning о размере чанка — предсуществующий) |

## 10. Фактические числа полного прогона

```
pytest -q   →   197 passed, 3 skipped, 578 warnings in 280.04s (0:04:40), exit 0
```

Было 191 тест (188 passed + 3 skip); добавлено 6 тестов S-5:
5 в `test_auth_api.py` (выдача кода, повтор/инвалидация, использованный и истёкший код,
401/403 на выдачу, контракт `resend-invite`) и 1 в `test_sprint12_api.py` (CSP);
плюс 4 в новом `test_documents_security.py` — итого 197 passed + 3 skip.

Проверки вне pytest:
* `Settings.model_fields["EXPOSE_OTP_CODE"].default is False`;
* `Settings(ENV="prod", EXPOSE_OTP_CODE=True, …)` → `ValueError` («Некорректная конфигурация
  для ENV=prod: EXPOSE_OTP_CODE…») — запрет в prod работает;
* в `notify.py` нет ни одной строки форматирования кода (`del code`, логи только канал и маска);
* `tsc -b --noEmit` → exit 0; `vite build` → exit 0 (6.87 s).

## 11. Ограничения и что осталось

* CSP для SPA — reverse-proxy (nginx/Docker, F-1/F-2), не код приложения.
* Старые документы с `mime=image/svg+xml` остаются в БД, но больше не отдаются как активный
  SVG; отдельная задача — миграция/вычистка таких записей (вне объёма S-5: миграции запрещены).
* `send_otp_code` сохранён как интерфейс доставки: когда появится Telegram-бот, код будет
  уходить в канал, а не в лог; сейчас доставка «manual» — код передаёт администратор.
* Код первичной регистрации живёт 10 минут и не продлевается: после истечения администратор
  выдаёт новый (старый автоматически гасится).
