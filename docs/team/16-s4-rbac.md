# 16 — S-4: RBAC на `/api/sync/push` и доверие `X-Forwarded-For`

**Дата:** 2026-11-25
**Исполнитель:** backend-auditor (задача t15, команда karier-improvements)
**Проект:** `C:\karier\karier\backend-v2`
**Статус:** реализовано; прогоны pytest — после согласованного окна (см. §7). Код и тесты — в рабочем дереве (не коммичены, как и остальной WIP владельца).

## 1. Проблема

`POST /api/sync/push` принимал офлайн-очередь от любого аутентифицированного сотрудника, а права проверялись «мягко»: при отсутствии `asset.create` всё равно разрешались `status`, `grounded`, `x`, `y`, `location_text`; `move` и `defect` не проверялись вовсе; `entity_id` не сверялся с карьером. Отдельно `client_ip()` безусловно доверял `X-Forwarded-For` — поддельный заголовок менял ключ rate-limit и IP в аудите.

## 2. Решение

### 2.1. Карта «операция/поле → право»

`app/services/sync.py`:

| Операция / поле | Требуемое право |
|---|---|
| `asset` + `update`, поле `status` | `asset.status.edit` |
| `asset` + `update`, поле `grounded` | `asset.status.edit` |
| `asset` + `update`, поля `x`, `y`, `location_text` | `asset.move` |
| `asset` + `update`, поля `name`, `attrs` | `asset.create` |
| `asset` + `insert` | `asset.create` |
| `move` + `update`/`insert` | `asset.move` |
| `defect` + `insert` | `defect.manage` |
| неизвестная операция | прав не требует (позже `rejected` — как раньше) |

Правило: для `asset` права собираются **по каждому полю patch** (клиент присылает произвольный patch), для `insert` дополнительно требуется `asset.create`.

### 2.2. Двухфазный push: 403/404 до изменений

`push()` теперь сначала вызывает `_check_push_permissions()` и `_check_push_entities()`, и только потом применяет операции:

* **403 `perm.denied`** — если хотя бы для одной операции пачки не хватает права; в `detail` перечислены операции и недостающие права. Ответ — `application/problem+json` с `code`, а не 500: `ApiError` обрабатывается общим обработчиком.
* **404 `asset.not_found`** — если `entity_id` (`asset`/`move`) или `asset_id` дефекта не существует, удалён, **или принадлежит другому карьеру** (`pit_id != текущий pit`). Проверка также до изменений, поэтому чужая пачка не даёт частичных эффектов.
* Дубликаты (`SyncOp` уже есть) и неизвестные операции — как раньше (`duplicate`/`rejected`, HTTP 200).

### 2.3. Границы карты

* `move`: перед созданием `AssetMove` вызывается `gis.check_bounds(db, asset.pit_id, x, y)` — вне карты операция `rejected` с текстом `asset.out_of_bounds` в `message` (HTTP 200, пачка не падает).
* `asset patch` с `x`/`y`: та же проверка **до** фиксации конфликта и setattr; нечисловые координаты → `rejected` «Некорректные координаты».

### 2.4. `X-Forwarded-For` только от доверенных прокси

`app/core/config.py`: новая настройка

```python
TRUSTED_PROXIES: str = ""          # CSV: IP или CIDR, например "127.0.0.1,10.0.0.0/8"
@property
def trusted_proxies(self) -> list[str]: ...
```

`app/core/rate_limit.py`:

```python
def client_ip(request) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy(peer, settings.trusted_proxies):
        return forwarded.split(",")[0].strip()   # первый IP цепочки
    return peer
```

* пустой allowlist (по умолчанию) — заголовок игнорируется полностью;
* прокси из allowlist — берётся **первый** IP из `X-Forwarded-For`;
* поддержаны IPv4/IPv6, CIDR; не-IP строка (например, `testclient`) сравнивается точно — это нужно тестам, в проде такую запись не ставить;
* тот же `client_ip` используется в аудите (`api/middleware.py`), поэтому IP в журнале тоже перестал быть подделываемым.

## 3. Изменённые файлы

| Файл | Что изменено |
|---|---|
| `app/core/config.py` | `TRUSTED_PROXIES` + property `trusted_proxies` |
| `app/core/rate_limit.py` | `_is_trusted_proxy()` (IP/CIDR), новый `client_ip()` |
| `app/services/sync.py` | `FIELD_PERMISSIONS`, `OP_PERMISSIONS`, `_operation_permissions`, `_check_push_permissions` (403), `_check_push_entities` (404), preflight в `push()`; проверка границ для `move` и `patch x/y`; убрана прежняя «мягкая» логика `allowed`-полей |
| `tests/test_sync_api.py` | +8 тестов S-4 (ниже) |
| `tests/test_security_ip.py` | новый файл: 6 юнит-тестов `client_ip` + 2 интеграционных на лимит входа |

Не трогались: `app/services/gis.py`, миграции, `src-v2`, `.env` (по контракту). `app/api/routers/sync.py` не менялся: проверки прав/карьера живут в сервисе, роутер остаётся тонким.

## 4. Контракт ответов

403 (пачка целиком отклонена, ничего не применено):

```json
{
  "type": "https://karier.local/errors/perm.denied",
  "title": "Недостаточно прав для операций синхронизации — asset/update: asset.status.edit",
  "status": 403,
  "code": "perm.denied",
  "detail": "Недостаточно прав для операций синхронизации — asset/update: asset.status.edit",
  "instance": "/api/sync/push",
  "request_id": "…"
}
```

404 (чужой/несуществующий entity):

```json
{"status": 404, "code": "asset.not_found", "detail": "Объект не найден", …}
```

Вне границ — HTTP 200, `results[i].status = "rejected"`, `message` содержит «Координаты вне карты…».

## 5. Тесты

`tests/test_security_ip.py` (новый):

1. пустой `TRUSTED_PROXIES` → XFF игнорируется, IP = peer;
2. доверенный прокси по IP → берётся первый IP цепочки (`203.0.113.7, 10.0.0.5` → `203.0.113.7`);
3. доверенный прокси по CIDR (`10.0.0.0/8`) → XFF применяется;
4. недоверенный peer → XFF игнорируется;
5. нет `request.client` → `unknown`;
6. точное не-IP совпадение (`testclient`) — для тестового клиента;
7. интеграционно: поддельный XFF при пустом allowlist **не обходит** лимит входа (3-я попытка → 429);
8. интеграционно: от доверенного прокси каждый XFF-IP — отдельный ключ лимита (429 нет).

`tests/test_sync_api.py` (+8):

1. `test_viewer_forbidden_status_patch` — viewer: 403 `perm.denied`, объект не изменился;
2. `test_viewer_and_contractor_forbidden_operations` — viewer/contractor: 403 на status/move/patch координат; viewer — 403 на дефект;
3. `test_operator_cannot_change_name_without_asset_create` — operator: 403 на `name`/`attrs`;
4. `test_operator_push_status_and_move_applied` — operator: status и move применяются (200), координаты/статус возвращаются;
5. `test_contractor_can_insert_defect` — contractor: дефект применяется, строка в БД появляется (потом мягко удаляется админом);
6. `test_push_rejects_out_of_bounds_move_and_patch` — move и patch x/y вне карты → `rejected`, объект не сдвинут;
7. `test_foreign_pit_entity_returns_404` — asset/move/defect с `entity_id` чужого `Pit` → 404 `asset.not_found` (объект и карьер убираются после теста);
8. существующие тесты sync (идемпотентность, конфликты, pull, move race) — поведение сохранено для admin.

## 6. Влияние на фронтенд и эксплуатацию

* Офлайн-клиент теперь получает **403 на всю пачку**, если прав не хватает хотя бы на одну операцию (раньше «лишние» поля тихо игнорировались). Это осознанно: тихое игнорирование скрывало обход RBAC. UI должен показать `detail` (русский) и предложить обновить права/повторить.
* `rejected` по границам приходит как раньше — HTTP 200 + `results[].status`, отдельного экрана не нужно.
* Администрирование: на стенде `TRUSTED_PROXIES` пуст (XFF игнорируется). За обратным прокси (nginx/Caddy/Docker) нужно указать его адрес, иначе все клиенты будут выглядеть одним IP и лимит входа/аудит будут неточными: `TRUSTED_PROXIES=127.0.0.1` (или подсеть прокси). Нельзя вписывать туда клиентские сети.
* `.env.example`/Docker (F-1) — при появлении reverse-proxy добавить `TRUSTED_PROXIES`; сейчас переменная необязательна.

## 7. Проверки (финальные, чистое окно)

| Проверка | Результат |
|---|---|
| `pytest -q tests/test_sync_api.py tests/test_security_ip.py` | **24 passed**, 26.74 с, exit 0 |
| `pytest -q` (полный, один прогон) | **188 passed, 3 skipped**, 307.86 с (5:07), exit 0 |

* `test_pull_returns_delta` в чистом окне **прошёл** — подтверждает, что прежние падения были следствием параллельного прогона (409 `no_change` / состояние `KTP-15`), а не S-4. Тест не менялся.
* После полного прогона `karier_test_db` не изменилась: 585 активных / 4700 объектов / 3788 связей / 87 сотрудников, тестовых сотрудников (`T*`/`TST-*`) — 0, alembic `0014_schema_snapshots`; изоляция S-9 работает.
* Параллельных pytest не было (подтверждено капитаном: S-9 закрыта, 188 passed ×2 без reset).

**Хронология промежуточных (загрязнённых) прогонов — для аудита:**

1. 23 passed, 1 failed — `test_foreign_pit_entity_returns_404`: `ForeignKeyViolation`, SQLAlchemy вставлял `Asset` раньше `Pit` (между моделями нет relationship). Исправлено в тесте: `db.add(pit); db.flush(); db.add(asset)`; отдельный прогон — **1 passed**.
2. 23 passed, 1 failed — `test_pull_returns_delta` при параллельном прогоне другого набора.
3. 22 passed, 2 failed — `test_pull_returns_delta` и `test_operator_push_status_and_move_applied`: загрязнение подтверждено (в `.pytest_cache/.../lastfailed` одновременно 15+ падений из `test_topology_api.py`, `test_auth_api.py`, `test_undo_restore.py`, которых поднабор не запускал; S-9-фикстура удаляет строки, созданные после её снимка → 401/409).

## 8. Ограничения и замечания

1. Приложение по-прежнему однокарьерное (`gis.get_pit` — первый активный), поэтому «чужой карьер» проверяется по `pit_id` текущего карьера; при появлении выбора карьера проверка станет «pit из запроса».
2. `device_id` в push не используется для прав/аудита — вне S-4.
3. Неизвестные поля patch молча игнорируются (как раньше); неизвестные операции → `rejected`.
4. `X-Forwarded-For` при доверенном прокси: берётся левый (клиентский) адрес; цепочку прокси не валидируем — стандартное допущение, но при нескольких прокси стоит перейти на `Forwarded`/список доверенных hop'ов.
5. `field_labels`/422 и прочие контракты не затрагивались.
6. `test_pull_returns_delta` (существующий тест) зависит от состояния `KTP-15`: если объект уже `off`, `POST /state` даёт 409 `no_change`, `change_log` не пополняется и тест падает. В чистом окне проходит; при параллельных прогонах — хрупок. Кандидат в S-9 (изоляция), в S-4 тест не менялся.

## 9. Откат

Изменения обратимы: `git stash push`/`git checkout` по 5 файлам; настройка `TRUSTED_PROXIES` необязательна (пустая = прежнее поведение «не доверять никому», что строже старого). Миграций нет.
