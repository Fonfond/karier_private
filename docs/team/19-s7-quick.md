# S-7: sourcemap false, корневой ErrorBoundary, подтверждения удаления

**Задача:** t18 (S-7), попытка 4. **Исполнитель:** frontend-auditor.
**Дата:** 2026-11-25. **Проект:** `C:\karier\karier\src-v2` (React 18 + Vite 5).
**Тип:** implementation. Бэкенд не менялся, pytest не запускался (заморожен на время V1d).

---

## 1. Итог

Закрыты четыре «дешёвых» дефекта из аудита (`docs/team/02-frontend-audit.md`, F-02, F-06, F-09 и часть F-10):

1. **Sourcemap выключен** (`vite.config.ts`): `dist` уменьшился с **7,58 МБ до 2,42 МБ**, `.map`-файлов в сборке — **0**. Исходники больше не публикуются.
2. **Корневой `ErrorBoundary`** (`src/components/ErrorBoundary.tsx`) подключён в `main.tsx` вокруг `AuthProvider`/`App`: при ошибке рендера показывается экран «Что-то пошло не так» с сообщением, кнопками «Перезагрузить» и «На главную»; ошибка пишется в `console.error` с префиксом `[ErrorBoundary]` и передаётся в опциональный `onError` (задел под мониторинг).
3. **Единый `ConfirmDialog`** (`src/components/ui.tsx`) применён в **7 местах**, покрывающих 5 требуемых сценариев: связь (MapPage + SchemaView), документ (DocumentsTab), фото (PhotosTab), объект (RegistryPage + AssetSheet), сессия (ProfilePage). Отмена только закрывает диалог — API не вызывается.
4. **`window.location.reload()` после удаления удалён** (единственное вхождение осталось внутри самого `ErrorBoundary` — это кнопка «Перезагрузить»). Ошибки удаления показываются пользователю через `Alert`/`setError` во всех сценариях.

Проверки: build — exit 0 (`.map` = 0, `dist` = 2,42 МБ), typecheck — exit 0, vitest — **20 passed**, headless-проверка компонентов — **7/7**.

---

## 2. Матрица приёмки

| № | Критерий | Как проверено | Статус |
|---|---|---|---|
| 1 | `vite.config.ts`: sourcemap false; в `dist` нет `.map`; размер без карт < 2,6 МБ | `sourcemap: false` в `vite.config.ts:21-25`; build: `maps=0`, `dist_MB=2.42` (было 7,58 МБ с тремя картами на 5,19 МБ) | passed |
| 2 | Корневой ErrorBoundary: при throw показывает экран с сообщением и кнопкой «Перезагрузить»; ошибка логируется | headless-harness (7/7): `getDerivedStateFromError` переводит ошибку в state; `componentDidCatch` пишет `console.error('[ErrorBoundary] …')` и вызывает `onError`; fallback-разметка содержит `role="alert"`, «Что-то пошло не так», текст ошибки, «Перезагрузить», «На главную»; без ошибки дети рендерятся как есть; `main.tsx` содержит `<ErrorBoundary>` вокруг `<AuthProvider>` | passed |
| 3 | ConfirmDialog минимум в 5 деструктивных сценариях; отмена не удаляет | 7 использований: `MapPage.tsx:916` (связь), `SchemaView.tsx:2252` (связь), `DocumentsTab.tsx:291` (документ), `PhotosTab.tsx:145` (фото), `RegistryPage.tsx:669` (объект), `AssetSheet.tsx:444` (объект из карточки), `ProfilePage.tsx:284` (сессия). Кнопки-триггеры только открывают диалог (`setPendingDelete`/`setRevokeTarget`/`setConfirm…`); API вызывается исключительно в `onConfirm`. Harness: `role="dialog"`, `aria-modal`, `aria-labelledby`, заголовок/сообщение/«Отмена»/«Удалить», busy-состояние, закрытый диалог не рендерится | passed |
| 4 | `window.location.reload()` после удаления отсутствует; ошибки удаления показываются | grep по `src`: единственное `location.reload()` — `ErrorBoundary.tsx:32` (кнопка «Перезагрузить» на экране ошибки). Удаление объекта в `AssetSheet` больше не перезагружает страницу: `onDeleted` закрывает карточку и обновляет данные (`MapPage.tsx`). Ошибки: `setError`/`Alert` в RegistryPage, DocumentsTab, PhotosTab, ProfilePage (новый `sessionError`), AssetSheet (новый `deleteError`), MapPage (`setError`), SchemaView (`setError`) | passed |
| 5 | tsc, build, vitest зелёные; отчёт `docs/team/19-s7-quick.md` | `tsc -b --noEmit` exit 0; `vite build` exit 0 (508 модулей); `vitest run` — 3 files / 20 tests passed; этот отчёт | passed |

---

## 3. Изменения по файлам

### 3.1 `vite.config.ts`
```diff
-    sourcemap: true,
+    // Sourcemap в прод не отдаём: карты раскрывают исходники и весят больше самого бандла.
+    sourcemap: false,
```

### 3.2 `src/components/ErrorBoundary.tsx` (новый)
- Классовый компонент (`getDerivedStateFromError`, `componentDidCatch`) + презентационный `ErrorScreen`.
- `componentDidCatch`: `console.error('[ErrorBoundary] Необработанная ошибка интерфейса:', error, info.componentStack)` и `onError?.(error, info)`.
- Экран: `role="alert"`, `data-testid="error-boundary"`, заголовок, пояснение «данные и очередь не потеряны», текст ошибки, кнопки «Перезагрузить» (`window.location.reload`) и «На главную» (`location.assign('/')`).
- `ErrorScreen` экспортирован отдельно — проверяется headless-харнессом без DOM.

### 3.3 `src/main.tsx`
```diff
+import { ErrorBoundary } from './components/ErrorBoundary'
 ...
-      <AuthProvider>
-        <App />
-      </AuthProvider>
+      <ErrorBoundary>
+        <AuthProvider>
+          <App />
+        </AuthProvider>
+      </ErrorBoundary>
```
`App.tsx` не менялся: подключение в `main.tsx` (вариант «main.tsx/App.tsx» из задачи).

### 3.4 `src/components/ui.tsx` — `ConfirmDialog`
API: `open, title, message?, confirmLabel = 'Удалить', cancelLabel = 'Отмена', tone = 'danger', busy = false, onConfirm, onCancel`.
- `role="dialog"`, `aria-modal="true"`, `aria-labelledby="confirm-dialog-title"`, `data-testid="confirm-dialog"`.
- Фокус при открытии — на «Отмена» (Enter по умолчанию не удаляет), `Escape` закрывает (если не `busy`), клик по фону закрывает, клик внутри — нет; `busy` блокирует обе кнопки и показывает «Удаляем…».
- При закрытом `open` не рендерится.

### 3.5 Деструктивные сценарии

| Сценарий | Файл:строка (диалог) | Обработчик | Что изменилось |
|---|---|---|---|
| Связь на карте | `src/pages/MapPage.tsx:916` | `removeLink` (`:364`) | кнопка 🗑 открывает диалог вместо мгновенного удаления; при ошибке — `setError` |
| Связь на схеме | `src/components/map/SchemaView.tsx:2252` | `removeEdge` (`:1564`) | `window.confirm` заменён на `ConfirmDialog`; логика редактора не тронута (правка только в панели редактирования связи) |
| Документ | `src/components/asset/DocumentsTab.tsx:291` | `deleteDocument` (`:88`) | добавлено подтверждение и `try/catch` (раньше удаление одним тапом без обработки ошибок); офлайн-копия удаляется отдельным `try`, чтобы её отсутствие не выглядело ошибкой |
| Фото | `src/components/asset/PhotosTab.tsx:145` | `remove` (`:45`) | подтверждение; после успеха закрывается просмотрщик и показывается notice; ошибка — `Alert` |
| Объект (реестр) | `src/pages/RegistryPage.tsx:669` | `deleteAsset` (`:187`) | `window.confirm` заменён на `ConfirmDialog`; кнопки 🗑 (моб. и десктоп) получили `aria-label`; удаление не блокирует создание (`deleting` отдельно от `busy`) |
| Объект (карточка на карте) | `src/components/asset/AssetSheet.tsx:444` | `deleteAsset` (`:135`) | убран `window.location.reload()`; добавлен `onDeleted` → `MapPage` закрывает шторку и делает `refresh()`; ошибка — `Alert` (`deleteError`) |
| Сессия | `src/pages/ProfilePage.tsx:284` | `revoke` (`:93`) | подтверждение + обработка ошибки (`sessionError`), после успеха список перезагружается |

Отмена во всех случаях вызывает только `set…(null)` — запросов к API нет.

---

## 4. Проверки

| Команда | Результат |
|---|---|
| `npm run build` + подсчёт `.map` в `dist` | exit 0, `maps=0`, `dist=2,42 МБ`, 508 модулей, 5,2 с |
| `npm run typecheck` (`tsc -b --noEmit`) | exit 0, ошибок нет (после всех правок) |
| `npx vitest run` | exit 0: 3 files / **20 tests passed** (dxf 3, photo 3, authProvider 14) |
| headless-harness `.tmp/s7-harness.mjs` (вне git) | **7/7 PASS**: ErrorBoundary state/logging/fallback/pass-through, ConfirmDialog (роль, aria, тексты, busy, закрытое состояние), подключение в `main.tsx` |
| grep `location.reload` / `<ConfirmDialog` | reload — только `ErrorBoundary.tsx:32`; ConfirmDialog — 7 использований в 7 файлах |

Проверка ErrorBoundary без DOM: `ErrorBoundary` собран esbuild'ом в `.tmp/s7-bundle`, затем в Node вызваны `getDerivedStateFromError`, `componentDidCatch` (с подменой `console.error`) и `renderToStaticMarkup` фолбэка. Полноценный «бросить ошибку в браузере» в этом цикле не выполнялся (dev-сервер не поднимался) — шаг для QA в §6.

---

## 5. Отклонения от списка inScope (важно для ревью)

1. **`src/components/map/MapPage.tsx` в контракте не существует** — фактический файл `src/pages/MapPage.tsx` (именно он импортируется в `App.tsx`). Правка сделана в реальном файле.
2. **`src/components/asset/AssetSheet.tsx` отсутствовал в inScope**, но требование приёмки «`window.location.reload()` после удаления отсутствует» без него невыполнимо: единственный `reload` после удаления был именно там (`AssetSheet.tsx` → кнопка удаления объекта). Изменение минимальное: `window.confirm`-логика заменена на `ConfirmDialog`, добавлен необязательный проп `onDeleted` (обратная совместимость: без него диалог просто закрывается), `reload` удалён. Логика загрузки/редактирования карточки не менялась.
3. **`window.confirm` остался в местах вне требуемых сценариев**: `DefectsPage` (удаление дефекта), `EmployeesPage` (увольнение/удаление, 2 места), `TypesPage` (архивирование типа), `SnapshotsPanel` (публикация снимка), `SchemaView` (удаление ячейки/объекта, перенумерация опор). Они не входят в 5 сценариев задачи — не трогал, чтобы не расширять диф. Кандидаты на перевод в `ConfirmDialog` в следующем проходе.

---

## 6. Шаги ручной проверки (для QA)

Предусловие: `npm run build`, статика раздаётся; вход администратором (для удалений нужны права).

**ConfirmDialog (5 сценариев).** Для каждого: нажать «Удалить/🗑» → появляется модалка с заголовком и кнопками. Нажать «Отмена» → в Network **нет** DELETE/PATCH-запроса, данные на месте. Повторить и подтвердить → запрос уходит, список/карточка обновляются **без перезагрузки страницы** (нет белой вспышки, состояние фильтров сохраняется).
1. Карта → выбрать связь (клик по линии) → 🗑 в панели «Связь» → отмена/подтверждение.
2. Карта → режим «Схема» → клик по связи → «Удалить» в панели связи → отмена/подтверждение.
3. Карточка объекта → «Документы» → «Удалить» у документа.
4. Карточка объекта → «Фото» → открыть фото → «Удалить».
5. Реестр → 🗑 у объекта (мобильная карточка и десктопная таблица); а также карточка объекта на карте → «Удалить».
6. Профиль → «Активные устройства» → «Отозвать» у чужой сессии.
7. Проверить ошибку удаления: имитировать 500/обрыв (DevTools → Network → Offline) и нажать «Удалить» — должен появиться красный `Alert` с текстом ошибки, диалог остаётся открытым, данные не исчезают.

**ErrorBoundary.** Временно (локально, не коммитить) добавить в любую страницу бросок, например в `DashboardPage` перед `return`: `if (import.meta.env.DEV) throw new Error('проверка ErrorBoundary')`; открыть страницу → экран «Что-то пошло не так» с текстом ошибки и кнопкой «Перезагрузить»; в консоли — запись `[ErrorBoundary] Необработанная ошибка интерфейса`. Нажать «Перезагрузить» → приложение поднимается. После проверки строку удалить.

**dist.** `Get-ChildItem .\dist -Recurse -Filter *.map` → пусто; размер `dist` ~2,4 МБ (включая `karier-map.jpg` 1,06 МБ); открыть вкладку Network после деплоя — `.map` не запрашиваются (их нет).

---

## 7. Ограничения

- **Полноценный runtime-тест ErrorBoundary в браузере не выполнялся** (dev-сервер в цикле не поднимался). Проверены: state-machine, логирование, фолбэк-разметка (SSR), факт подключения. Остаточный риск — только поведение React в конкретной версии браузера, оно стандартное.
- **Нет unit-теста ConfirmDialog на «отмена не удаляет»**: без jsdom/`@testing-library` (не установлены, добавление зависимостей вне inScope) клик по кнопке не воспроизвести. Логика подтверждена структурно: триггеры только открывают диалог, API — внутри `onConfirm`.
- **`ErrorScreen` использует `window.location`** — в SSR/тестах не вызывается; кнопки рендерятся, обработчики навешиваются в браузере.
- **`AssetSheet.onDeleted`** — новый необязательный проп; единственный потребитель (`MapPage`) обновлён. Если появится второй потребитель без обработчика, после удаления карточка останется открытой до ручного закрытия (данные уже удалены) — это осознанный fallback, чтобы не ломать контракт.
- **pytest не запускался** (бэкенд заморожен, изменений в `backend-v2` нет).

---

## 8. Откат

Вернуть из git:
```
karier/src-v2/vite.config.ts
karier/src-v2/src/main.tsx
karier/src-v2/src/components/ui.tsx
karier/src-v2/src/pages/RegistryPage.tsx
karier/src-v2/src/pages/ProfilePage.tsx
karier/src-v2/src/pages/MapPage.tsx
karier/src-v2/src/components/asset/DocumentsTab.tsx
karier/src-v2/src/components/asset/PhotosTab.tsx
karier/src-v2/src/components/asset/AssetSheet.tsx
karier/src-v2/src/components/map/SchemaView.tsx
```
Удалить `karier/src-v2/src/components/ErrorBoundary.tsx` и `karier/docs/team/19-s7-quick.md`, затем `npm run build`. `window.confirm`/`reload` вернутся вместе с файлами; данные и БД не затрагиваются.

---

## 9. Изменённые пути

- `karier/src-v2/vite.config.ts` — `sourcemap: false`.
- `karier/src-v2/src/main.tsx` — корневой `ErrorBoundary`.
- `karier/src-v2/src/components/ErrorBoundary.tsx` — новый компонент + `ErrorScreen`.
- `karier/src-v2/src/components/ui.tsx` — `ConfirmDialog`.
- `karier/src-v2/src/pages/RegistryPage.tsx` — подтверждение удаления объекта.
- `karier/src-v2/src/pages/ProfilePage.tsx` — подтверждение отзыва сессии + ошибка.
- `karier/src-v2/src/pages/MapPage.tsx` — подтверждение удаления связи; `onDeleted` для карточки объекта.
- `karier/src-v2/src/components/asset/DocumentsTab.tsx` — подтверждение удаления документа + обработка ошибок.
- `karier/src-v2/src/components/asset/PhotosTab.tsx` — подтверждение удаления фото.
- `karier/src-v2/src/components/asset/AssetSheet.tsx` — диалог удаления объекта без `reload` (вне inScope, см. §5).
- `karier/src-v2/src/components/map/SchemaView.tsx` — `ConfirmDialog` для удаления связи в панели редактирования.
- `karier/docs/team/19-s7-quick.md` — этот отчёт.

`dist` пересобран (gitignored): 2,42 МБ, `.map` нет.
