# S-6: офлайн-старт и скоуп SW-кэша по пользователю

**Задача:** t17 (S-6), попытка 2. **Исполнитель:** frontend-auditor.
**Дата:** 2026-11-25. **Проект:** `C:\karier\karier\src-v2` (React 18 + Vite 5 + PWA).
**Тип:** implementation. Код бэкенда не менялся.

---

## 1. Итог

Закрыты два дефекта, найденных в аудите фронтенда (`docs/team/02-frontend-audit.md`, пункты F-01 и F-03):

1. **Холодный старт без сети больше не разлогинивает.** `AuthProvider` различает `ApiError(401)` (сессии нет — на `/login`) и сетевую ошибку `TypeError`/`AbortError` (сессию и флаг `karier-session` сохраняем, пользователя поднимаем из кэша, показываем баннер «Офлайн»). Логика решения вынесена в чистые функции `restoreSession()` / `applyRestoreResult()` и покрыта vitest-тестами.
2. **API-кэш service worker'а скоуплен по `user.id`.** Имя кэша содержит build-id сборки и id пользователя, TTL 5 минут, лимит 100 записей, `activate` удаляет старые кэши, выход из приложения полностью очищает API-кэши и метку пользователя (сценарий A→выход→B). `karier-map.jpg` (1,06 МБ) убран из precache.

Проверки: typecheck — 0 ошибок; vitest — **20 passed** (14 из них новые в `authProvider.test.ts`); build — exit 0; отдельный harness над `public/sw.js` — **10/10 проверок**.

---

## 2. Матрица приёмки

| № | Критерий | Как проверено | Статус |
|---|---|---|---|
| 1 | Авиарежим + холодный старт: приложение открывается, пользователь не разлогинен, виден баннер «офлайн» | unit: `restoreSession(TypeError)` → `offline` + `user = cached`; `applyRestoreResult` → `setUser(cached)`, `setOffline(true)`, `clearSessionHint` не вызывается; `OfflineBanner` рендерится с текстом «Офлайн» и `role="status"` (renderToStaticMarkup). Ручной сценарий — §6. | passed |
| 2 | 401 по-прежнему ведёт на `/login`; сетевая ошибка не стирает сессию и не снимает `karier-session` | unit: `ApiError(401)` → `unauthenticated`, `clearSession: true`; `applyRestoreResult` вызывает `clearSessionHint()`, `clearCachedUser()`, `setAccessToken(null)`, `setUser` не вызывает; для сети — `clearSession: false` (тест «сеть недоступна: сессия и флаг сохранены»). `RequireAuth` не менялся: при `user = null` → `Navigate to="/login"` (`src/auth/guards.tsx:10-11`). | passed |
| 3 | Имя кэша SW содержит build-id; `activate` удаляет старые кэши | harness: shell-кэш `karier-v3-<build-id>-shell` (build-id = hash entry-чанка из `/index.html`); после `activate` удалены `karier-v2-shell`, `karier-v2-api`, `karier-v3-<старый build>-shell`, при этом `karier-sw-meta` сохранён. Для текущей сборки: `karier-v3-x53xab-shell` (entry `index-CJrJiaKP.js`). | passed |
| 4 | API-кэш скоупится по `user.id`, TTL ≤ 5 минут, лимит записей; при logout очищается | harness: `karier-v3-<build>-api-user-a`, 105 GET → в кэше ≤ 100; запись с `x-karier-cached-at` старше 6 мин не отдаётся и удаляется; после `karier-clear-cache` нет ни одного `*-api-*`, meta удалён. TTL `5 * 60 * 1000` — `public/sw.js:18`. | passed |
| 5 | Сценарий A→выход→B: данные A не находятся в кэше | harness: A наполняет кэш (`payload-A`), logout чистит всё, B в офлайне получает 503 `code=offline` (не `payload-A`); кэши A и B — разные имена. | passed |
| 6 | `karier-map.jpg` (1 МБ) убран из precache `SHELL_URLS` | `public/sw.js:14`: `SHELL_URLS = ['/', '/index.html']`; harness: в shell-кэше после install нет `/karier-map.jpg`; в `dist/sw.js` 0 вхождений `karier-map`. | passed |
| 7 | Тест AuthProvider различает `ApiError(401)` и `TypeError` сети; pytest/vitest зелёные | `src/auth/authProvider.test.ts`: 14 тестов, среди них 7 про различение (401 / TypeError / AbortError / `Load failed` / 5xx / успешный refresh / предикаты). vitest: 3 files, **20 passed**, exit 0. Бэкенд не менялся, pytest не запускался (см. §7). | passed |
| 8 | Отчёт `docs/team/18-s6-offline.md` с шагами ручной проверки | этот файл, §6. | passed |

---

## 3. Что изменено

### 3.1 `src/auth/AuthProvider.tsx` (главное)

- **Различение ошибок:** `isUnauthorizedError()` (только `ApiError.status === 401`) и `isNetworkError()` (`TypeError`, `AbortError`/`TimeoutError`, сообщения `Failed to fetch` / `Load failed` / `NetworkError`). Раньше любой сбой bootstrap приводил к `removeItem(SESSION_HINT)` и экрану входа.
- **`restoreSession(refresh, cachedUser)`** (`AuthProvider.tsx:58`) — чистая async-функция, возвращает одно из:
  - `authenticated` (refresh прошёл);
  - `unauthenticated` + `clearSession: true` — только 401;
  - `offline` + `user` из кэша (сеть недоступна);
  - `degraded` + `user` из кэша (5xx/иное — сессию не сбрасываем).
- **`applyRestoreResult(result, effects)`** (`:89`) — единственное место, где решается судьба сессии: 401 → чистка токена/подсказки/кэша; сеть/сервер → пользователь из кэша и баннер. Вызов из bootstrap-эффекта: `:243-269`.
- **Кэш последнего пользователя:** ключ `karier-last-user` (`:27`), хранится только профиль (`id`, `tab_no`, `full_name`, `role`, `permissions`, …), **без токенов**. Запись: при `login`/`verifyMfa`/`refreshUser`/`applyUser`/успешном bootstrap; чтение — при старте; очистка — при выходе и при 401. Валидация `isUser()` отсекает битый/чужой JSON (`readCachedUser`, `:126`).
- **Баннер «Офлайн»** (`OfflineBanner`, `:203`): фиксированная плашка `role="status" aria-live="polite"` с текстом «Офлайн. Нет сети — показаны сохранённые данные…», `data-testid="offline-banner"`, кнопка «Скрыть» (чтобы не закрывать управление картой). Показывается при `offline`, исчезает при событии `online`; появляется/снимается по `window.online/offline` (`:272-283`).
- **`logout` стал офлайн-устойчивым:** `api.logout()` в `try/catch` — при отсутствии сети локальный выход всё равно происходит (важно для общего планшета), в `finally` чистятся токен, `karier-session`, `karier-last-user` и отправляется `karier-clear-cache` в SW (`:316-324`). Раньше при сетевой ошибке выход падал.
- **Связь с SW:** при появлении `user.id` отправляется `{type:'karier-user', userId}` (`:287-290`), при выходе — `{type:'karier-clear-cache'}`; если контроллера ещё нет, сообщение уходит через `navigator.serviceWorker.ready` (`notifyServiceWorker`, `:185`).
- Контекст дополнен полем `offline: boolean` (обратная совместимость: существующие потребители поле не читают).

### 3.2 `public/sw.js` (переписан, 380 строк)

| Элемент | Реализация |
|---|---|
| Build-id | `fetchBuildId()` (`sw.js:36`): `fetch('/index.html', {cache:'no-store'})` → первый `/assets/<entry>.js` → djb2-hash → base36. Мемоизируется на время жизни SW; при недоступности сети — `dev` (самовосстанавливается после перезапуска SW). |
| Имена кэшей | shell: `karier-v3-<buildId>-shell`; API: `karier-v3-<buildId>-api-<userId>`; метка пользователя: `karier-sw-meta` (`apiCacheName`, `:57`). |
| `install` | кэширует только `['/', '/index.html']` (без `karier-map.jpg`), ошибки сети не ломают установку, затем `skipWaiting()` (`:290`). |
| `activate` | удаляет все кэши, кроме `karier-v3-<текущий build>-*` и `karier-sw-meta`, затем `clients.claim()` (`:305`). |
| API GET | network-first; успешный JSON кэшируется с заголовком `x-karier-cached-at`; при офлайне отдаётся своя запись пользователя, иначе 503 `{detail:'Нет сети…', code:'offline'}` (`handleApiRequest`). |
| TTL | `API_TTL_MS = 5 * 60 * 1000` (`:18`); просроченная запись удаляется при первом обращении. |
| Лимит | `API_MAX_ENTRIES = 100` (`:19`), FIFO-обрезка после записи (`trimApiCache`). |
| Не кэшируется | `Cache-Control: no-store/private`, не-JSON, ответы > 512 КБ; приватные пути `/api/auth`, `/api/sync`, `/api/media`, `/api/documents`, **`/api/map/layers/`** (подложка с S-5 под авторизацией; добавлено в `isPrivateApi`, `:136`). |
| Пользователь | `message {type:'karier-user', userId}` → `currentUserId` + запись в `karier-sw-meta` (переживает перезапуск SW); при отсутствии пользователя API-кэш не читается и не пишется (fail-safe). |
| Выход | `message {type:'karier-clear-cache'}` → удаляются **все** `*-api-*` кэши и `karier-sw-meta` (`clearUserCaches`, `:108`). |
| Оболочка/навигация | shell-кэш текущего build-id, network-first для навигации; статика — cache-first с добором в shell-кэш. |
| Прочее | background sync `karier-outbox` и `karier-skip-waiting` сохранены. |

### 3.3 `src/auth/authProvider.test.ts` (новый, 14 тестов)

- `restoreSession`: 401 → `unauthenticated/clearSession`; `TypeError('Failed to fetch')` → `offline` + cached user; сеть без кэша → `offline` + `null`; `AbortError` и Safari `Load failed` → `offline`; 5xx → `degraded` + cached; успешный refresh → `authenticated`.
- `isUnauthorizedError` / `isNetworkError`: 401 ≠ сетевая ошибка, `TypeError` ≠ 401, `ApiError(503)` ≠ сетевая.
- `applyRestoreResult`: сеть — `clearSessionHint`/`clearCachedUser` **не** вызываются, баннер включён; 401 — вызываются, `setUser` не вызывается; успех — `persistUser` + баннер выключен.
- `OfflineBanner`: в разметке есть «Офлайн», «Нет сети», `role="status"`, `aria-live="polite"`, кнопка скрытия.
- Кэш последнего пользователя: сохранение/чтение профиля, отсутствие слова `token` в значении, очистка при выходе, устойчивость к битому JSON.

### 3.4 Что сознательно НЕ менялось

- `src/lib/api.ts`, `src/lib/sync.ts` — в inScope, но правок не потребовалось: сетевые ошибки `fetch` уже пробрасываются наружу как `TypeError` (их и различает `AuthProvider`); `sync.ts` к холодному старту и к кэшу SW отношения не имеет.
- `src/auth/guards.tsx`, `src/components/AppShell.tsx`, `src/main.tsx` — вне inScope; работают с новым поведением без изменений (`logout` теперь не бросает при офлайне, поэтому навигация в `handleLogout` выполняется и без сети).
- Бэкенд, БД, `SchemaView.tsx` — не трогались.

---

## 4. Проверки (команды и результаты)

| Команда | Результат |
|---|---|
| `powershell -NoProfile -Command "cd C:\karier\karier\src-v2; npm.cmd run typecheck"` | exit 0, ошибок нет (проверено трижды, последний раз на финальном коде) |
| `powershell -NoProfile -Command "cd C:\karier\karier\src-v2; npx.cmd vitest run"` | exit 0: **3 files / 20 tests passed** (dxf 3, photo 3, authProvider 14), 1,3 с |
| `powershell -NoProfile -Command "cd C:\karier\karier\src-v2; npm.cmd run build"` | exit 0, 508 модулей, 5,8 с; `dist/sw.js` побайтово совпадает с `public/sw.js` (сравнение SHA-256) |
| `node --check public/sw.js` | exit 0 (синтаксис) |
| `node .tmp/sw-harness.mjs` (временный harness, вне git) | **10/10 PASS**: build-id в имени shell-кэша; нет `/karier-map.jpg` в precache; `activate` чистит старые кэши и сохраняет meta; API-кэш `...-api-user-a`; офлайн отдаёт кэш; TTL 6 мин → 503 + удаление; лимит 100; `no-store` не кэшируется; `/api/auth` и `/api/map/layers` не перехватываются; A→logout→B → 503 без данных A; кэши A и B различаются |

Текущая сборка: entry `index-CJrJiaKP.js` → build-id `x53xab` → кэш `karier-v3-x53xab-shell`.

---

## 5. Как это работает (короткая схема)

```
старт приложения
  └─ есть karier-session? ──нет──► экран входа
        └─ api.refresh()
             ├─ ok ──────────────► user + karier-last-user, offline=false
             ├─ ApiError(401) ───► чистим karier-session, karier-last-user, токен → /login
             └─ TypeError/abort ─► user из karier-last-user, offline=true, баннер «Офлайн»
                                   (karier-session сохраняется — сессия восстановится при сети)

после входа/восстановления: SW получает {type:'karier-user', userId}
  └─ API-кэш: karier-v3-<build>-api-<userId>, TTL 5 мин, ≤100 записей

выход: api.logout() (при офлайне — игнорируем ошибку) → SW {type:'karier-clear-cache'}
  └─ удалены все *-api-* и karier-sw-meta; локальный кэш пользователя очищен
```

---

## 6. Шаги ручной проверки (для QA)

Предусловие: `src-v2` собран (`npm run build`), статика раздаётся (Vercel/`vite preview`), первый визит — онлайн.

1. **Кэши после входа.** DevTools → Application → Cache Storage. Ожидается: `karier-v3-<buildId>-shell`, `karier-sw-meta`; после открытия Реестра/Карты — `karier-v3-<buildId>-api-<user.id>`. В shell-кэше **нет** записи `/karier-map.jpg`.
2. **Холодный старт в авиарежиме.** Войти, открыть «Реестр» и «Карту» (наполнить кэш), затем DevTools → Network → Offline (или авиарежим), **закрыть вкладку**, открыть приложение заново. Ожидается: приложение открывается, пользователь тот же, внизу баннер «Офлайн. Нет сети — показаны сохранённые данные…», `localStorage['karier-session'] === '1'`, `localStorage['karier-last-user']` содержит профиль без токенов.
3. **Баннер.** Кнопка «×» скрывает плашку; при возврате сети (Offline → Online) плашка исчезает сама; при повторном уходе в офлайн появляется снова.
4. **401 не сломан.** Онлайн: Application → Cookies → удалить refresh-cookie (например, `refresh_token`) → перезагрузить. Ожидается: редирект на `/login`, `karier-session` и `karier-last-user` удалены, баннера нет.
5. **Сеть не стирает сессию.** Офлайн → перезагрузить страницу (тот же пользователь, баннер) → проверить, что `karier-session` остался `'1'`; вернуть сеть и перезагрузить — сессия восстанавливается штатно.
6. **A → выход → B.** Войти как A, открыть «Реестр» (кэш A заполнен), нажать «Выйти». Cache Storage: ни одного `*-api-*`, `karier-sw-meta` отсутствует. Войти как B, уйти в офлайн, открыть «Реестр»: данных A нет — либо ошибка сети, либо 503 «Нет сети, данные недоступны».
7. **TTL.** Войти, открыть «Реестр», подождать > 5 минут (или сдвинуть системное время), уйти в офлайн, перезагрузить: для этого экрана кэш уже не отдаётся; запись удаляется при первом обращении.
8. **Обновление версии.** Пересобрать/задеплоить (build-id изменится), перезагрузить: старые `karier-v3-<old>-*` удалены, появился кэш с новым build-id; `karier-sw-meta` пережил обновление (пользователь не потерян).
9. **Подложка карты.** Открыть карту: `/api/map/layers/<id>/image` идёт с Bearer-токеном, SW его не кэширует (запрос виден в Network с Authorization), карта отображается.

---

## 7. Ограничения и риски

1. **build-id выводится из `/index.html`, а не инжектится сборкой** (правка `vite.config.ts`/`main.tsx` вне inScope). Если при `install`/`activate` сеть недоступна, id = `dev`; после перезапуска SW (следующая загрузка страницы) он вычисляется заново, а `karier-v3-dev-*` удаляются при `activate`. Проверено harness'ом. Если позже понадобится «настоящий» build-id, достаточно заменить `fetchBuildId()` на чтение `__BUILD_ID__`, подставляемого плагином Vite.
2. **TTL — ленивый:** просроченная запись удаляется при первом чтении, а не фоновым таймером (SW не держит таймеры). Это не влияет на корректность: просроченное не отдаётся.
3. **Лимит 100 записей** — FIFO по порядку ключей Cache API (в Chromium совпадает с порядком вставки; в других движках порядок не гарантирован, но лимит соблюдается).
4. **Кэш API не шифруется.** На общем планшете данные удаляются при штатном выходе; при аварийном закрытии браузера данные прошлого пользователя живут в CacheStorage не дольше 5 минут (TTL) и не читаются без метки пользователя. Компромисс зафиксирован здесь.
5. **`karier-map.jpg` больше не precache.** Файл остаётся в `public/` (используется только старым легаси-приложением и не нужен PWA); offline-подложка обеспечивается сервером + авторизованным `requestBlob` (S-5), а не precache.
6. **Отдельного теста на `sw.js` в репозитории нет** (inScope разрешает только `authProvider.test.ts`). Логика SW проверена временным harness'ом `.tmp/sw-harness.mjs` (вне git, 10 проверок). Если нужно закрепить в CI — это отдельная задача (например, `src/sw.test.ts` с тем же harness, потребует решения по структуре SW-модуля).
7. **pytest не запускался:** в этом цикле не менялся ни один файл `backend-v2`, а в контракте verify перечислены только фронтенд-команды. Последний полный бэкенд-прогон (t16) — 197 passed, 3 skipped; изменений, влияющих на бэкенд, нет.
8. **Ручная проверка в реальном браузере/на устройстве не выполнялась** (по контракту цикла dev-сервер не поднимался). Шаги §6 — для QA; unit- и harness-проверки покрывают логику решений, но не реальный lifecycle SW в конкретном браузере.

---

## 8. Откат

Откатить четыре файла (git):

```
karier/src-v2/src/auth/AuthProvider.tsx
karier/src-v2/public/sw.js
karier/src-v2/src/auth/authProvider.test.ts   (удалить)
karier/docs/team/18-s6-offline.md             (удалить)
```

Затем `npm run build`. Пользовательские данные: после отката в CacheStorage останутся только кэши `karier-v3-*`/`karier-sw-meta` (SW снова будет `karier-v2` и удалит их при следующем `activate`); в localStorage — `karier-last-user`, который старый код игнорирует и не читает. Секретов в них нет.

---

## 9. Изменённые пути

- `karier/src-v2/src/auth/AuthProvider.tsx` — различение 401/сети, кэш пользователя, баннер, офлайн-устойчивый logout, связь с SW.
- `karier/src-v2/public/sw.js` — build-id в именах кэшей, скоуп по `user.id`, TTL/лимит, очистка при выходе, precache без `karier-map.jpg`.
- `karier/src-v2/src/auth/authProvider.test.ts` — новый файл, 14 тестов.
- `karier/docs/team/18-s6-offline.md` — этот отчёт.

Артефакты сборки (`src-v2/dist/**`, gitignored) пересобраны; `dist/sw.js` идентичен `public/sw.js`.
